import pandas as pd
import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text
from datetime import datetime, timedelta
import time
from data.polygon_client import PolygonWrapper
from config.settings import DB_URI
from utils.market_clock import MarketClock
from utils.logger import logger
from utils.networking import retry_with_backoff

engine = create_engine(DB_URI)
poly = PolygonWrapper()

from config.model_config import ModelConfig

MACRO_SYMBOLS = {
    "VIX": getattr(ModelConfig, 'VIX_SYMBOL', '^VIX'), # Global risk proxy ticker
    "DXY": getattr(ModelConfig, 'DXY_SYMBOL', 'DX-Y.NYB'), # Dollar Index
}

def ingest_macro_data(start_date: str, end_date: str, force: bool = False):
    """
    Fetch VIX and other macro indicators with Range Guard.
    """
    # ... (Create table code omitted, assumes existing) ...
    # Wait, I should not omit the table creation if I am replacing the function def. 
    # But I am replacing lines 24-77.
    
    # --- Initialize Sync Metadata table ---
    with engine.connect() as conn:
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS sync_metadata (
                symbol TEXT, 
                component TEXT, 
                last_synced TIMESTAMP, 
                PRIMARY KEY (symbol, component)
            )
        """))
        conn.commit()

    stats = {"success": 0, "failed": 0, "rows": 0}
    target_start = pd.to_datetime(start_date).replace(tzinfo=None)
    target_end = pd.to_datetime(end_date).replace(tzinfo=None)

    @retry_with_backoff(tag="MACRO")
    def fetch_macro_with_retry(ticker, s_str, e_str, use_yfinance=False):
        if use_yfinance:
            from utils.symbol_mapper import to_yfinance_ticker
            yf_ticker = to_yfinance_ticker(ticker)
            import yfinance as yf
            yf_data = yf.download(yf_ticker, start=s_str, end=e_str, progress=False, interval="1d")
            if yf_data.empty: return []
            yf_data = yf_data.reset_index()
            yf_data.columns = [(str(c[0]) if isinstance(c, tuple) else str(c)).strip().lower() for c in yf_data.columns]
            date_col = next((c for c in yf_data.columns if 'date' in c or 'index' in c), None)
            bars = []
            if date_col:
                for _, row in yf_data.iterrows():
                    try:
                        def clean(val, type_fn):
                            return type_fn(val) if not pd.isna(val) else None
                        bars.append({'timestamp': int(row[date_col].timestamp() * 1000), 'close': clean(row['close'], float)})
                    except: continue
            return bars
        else:
            poly_ticker = ticker.replace("^", "I:") if ticker == "^VIX" else ticker
            return poly.get_aggs(poly_ticker, 1, "day", s_str, e_str)

    for metric, ticker in MACRO_SYMBOLS.items():
        logger.info(f"Processing Macro: {metric}...", tag="MACRO")
        fetch_ranges = []
        
        if force:
            logger.warning(f"Force Mode: Fetching {start_date} -> {end_date}", tag="MACRO")
            fetch_ranges.append((target_start, target_end, 'FULL'))
        else:
            try:
                query = text("SELECT MIN(time), MAX(time) FROM macro_data WHERE metric = :metric")
                with engine.connect() as conn:
                    res = conn.execute(query, {"metric": metric}).fetchone()
                    min_dt, max_dt = res if res else (None, None)
                
                if min_dt and max_dt:
                    min_dt, max_dt = pd.to_datetime(min_dt).replace(tzinfo=None), pd.to_datetime(max_dt).replace(tzinfo=None)
                    if target_start < min_dt - pd.Timedelta(days=1):
                        fetch_ranges.append((target_start, min_dt - pd.Timedelta(days=1), 'HEAD'))
                    if target_end > max_dt + pd.Timedelta(days=1):
                        fetch_ranges.append((max_dt + pd.Timedelta(days=1), target_end, 'TAIL'))
                    
                    if not fetch_ranges:
                        logger.success(f"Synchronized ({min_dt.date()} to {max_dt.date()}) for {metric}.", tag="MACRO")
                        stats["success"] += 1
                        continue
                else:
                    fetch_ranges.append((target_start, target_end, 'FULL'))
            except Exception as e:
                logger.error(f"DB Check failed for {metric}: {e}", tag="MACRO")
                fetch_ranges.append((target_start, target_end, 'FULL'))

        for s_dt, e_dt, gap_type in fetch_ranges:
            s_str, e_str = s_dt.strftime('%Y-%m-%d'), e_dt.strftime('%Y-%m-%d')
            two_years_ago = (MarketClock.now() - timedelta(days=720)).replace(tzinfo=None)
            use_yfinance = (s_dt < two_years_ago) or ticker.startswith('^')
            
            try:
                bars = fetch_macro_with_retry(ticker, s_str, e_str, use_yfinance=use_yfinance)
                
                if not bars:
                    if gap_type in ['HEAD', 'FULL']:
                        logger.warning(f"Silent Discovery: No macro history for {metric} in {s_str}->{e_str}. Marking as synched.", tag="MACRO")
                        with engine.connect() as conn:
                            conn.execute(text("""
                                INSERT INTO sync_metadata (symbol, component, last_synced)
                                VALUES (:symbol, 'macro_history', :now)
                                ON CONFLICT (symbol, component) DO UPDATE SET last_synced = EXCLUDED.last_synced
                            """), {"symbol": metric, "now": MarketClock.now()})
                            conn.commit()
                    continue
                    
                df = pd.DataFrame(bars)
                df['time'] = pd.to_datetime(df['timestamp'], unit='ms')
                df['metric'] = metric
                df['value'] = df['close']
                final_records = [{k: (None if pd.isna(v) else v) for k, v in r.items()} for r in df[['time', 'metric', 'value']].to_dict(orient='records')]
                for record in final_records:
                    if hasattr(record['time'], 'to_pydatetime'):
                        record['time'] = record['time'].to_pydatetime()
                
                with engine.connect() as conn:
                    stmt = text("""
                        INSERT INTO macro_data (time, metric, value)
                        VALUES (:time, :metric, :value)
                        ON CONFLICT (time, metric) DO UPDATE SET value = EXCLUDED.value;
                    """)
                    conn.execute(stmt, final_records)
                    conn.commit()
                
                logger.success(f"Saved {len(df)} rows for {metric} ({gap_type}).", tag="MACRO")
                stats["success"] += 1
                stats["rows"] += len(df)
            except Exception as e:
                logger.error(f"Hard Failure for {metric}: {e}", tag="MACRO")
                stats["failed"] += 1
            
            time.sleep(2)
    return stats

if __name__ == "__main__":
    # Initialize Universal Ingestion Logger for standalone runs
    logger.setup_ingestion_logging()
    
    # Use the lookback required for indicators (Z-score, etc)
    lookback_days = int((ModelConfig.DAILY_ML_TRAINING_WINDOW + ModelConfig.STRUCTURAL_WARMUP_DAYS) * ModelConfig.CALENDAR_TO_TRADING_SCALAR)
    start_dt = pd.Timestamp(ModelConfig.START_DATE) - pd.Timedelta(days=lookback_days)
    
    logger.audit(f"Starting standalone Macro Ingestion from {start_dt.date()}", tag="MACRO")
    ingest_macro_data(start_dt.strftime('%Y-%m-%d'), ModelConfig.END_DATE)
