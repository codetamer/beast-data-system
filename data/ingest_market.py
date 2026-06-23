import pandas as pd
import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime
from sqlalchemy import create_engine, text
from datetime import timedelta
from data.polygon_client import PolygonWrapper
from config.settings import DB_URI
from config.model_config import ModelConfig
from utils.market_clock import MarketClock
from utils.logger import logger
from utils.networking import retry_with_backoff
from data.validator import DataValidator

engine = create_engine(DB_URI)
poly = PolygonWrapper()

def validate_bars(bars: list, ticker: str) -> list:
    """Basic sanity checks for OHLCV data."""
    valid_bars = []
    for b in bars:
        try:
            # Check for non-negative values and logical OHLC relationships
            if b['open'] <= 0 or b['high'] <= 0 or b['low'] <= 0 or b['close'] <= 0:
                continue
            if b['high'] < min(b['open'], b['close']) or b['low'] > max(b['open'], b['close']):
                continue
            if b['high'] < b['low']:
                continue
            valid_bars.append(b)
        except (KeyError, TypeError):
            continue
    
    if len(valid_bars) < len(bars):
        logger.warning(f"Dropped {len(bars) - len(valid_bars)} invalid bars for {ticker}", tag="MARKET")
    return valid_bars

def ingest_market_data(tickers: list[str], start_date: str, end_date: str, force: bool = False):
    """
    Fetch OHLCV data with Range Guard, Sync Sentinel, and Silent Discovery.
    """
    import time
    
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
    
    utc_now = pd.Timestamp.now(tz='UTC').replace(tzinfo=None)
    utc_yesterday = (utc_now - pd.Timedelta(days=1)).normalize()
    
    if target_end > utc_yesterday:
        target_end = utc_yesterday

    @retry_with_backoff(tag="MARKET")
    def fetch_bars_with_retry(ticker, s_str, e_str, use_yfinance=False):
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
                        
                        bars.append({
                            'timestamp': int(row[date_col].timestamp() * 1000),
                            'open': clean(row.get('open'), float),
                            'high': clean(row.get('high'), float),
                            'low': clean(row.get('low'), float),
                            'close': clean(row.get('close'), float),
                            'volume': clean(row.get('volume'), float),
                            'adj_open': clean(row.get('adj open', row.get('open')), float),
                            'adj_high': clean(row.get('adj high', row.get('high')), float),
                            'adj_low': clean(row.get('adj low', row.get('low')), float),
                            'adj_close': clean(row.get('adj close', row.get('close')), float),
                            'adj_volume': clean(row.get('volume'), float)
                        })
                    except: continue
            return bars
        else:
            bars_adj = poly.get_aggs(ticker, 1, "day", s_str, e_str, adjusted=True)
            bars_raw = poly.get_aggs(ticker, 1, "day", s_str, e_str, adjusted=False)
            raw_map = {b['timestamp']: b for b in bars_raw}
            for b in bars_adj:
                raw = raw_map.get(b['timestamp'], b)
                b['adj_open'], b['adj_high'], b['adj_low'], b['adj_close'], b['adj_volume'] = b['open'], b['high'], b['low'], b['close'], b['volume']
                b['open'], b['high'], b['low'], b['close'], b['volume'] = raw['open'], raw['high'], raw['low'], raw['close'], raw['volume']
            return bars_adj

    for ticker in tickers:
        logger.info(f"Processing {ticker}...", tag="MARKET")
        fetch_ranges = []
        if force:
            logger.warning(f"Force Mode: Fetching {start_date} -> {end_date} for {ticker}", tag="MARKET")
            fetch_ranges.append((target_start, target_end, 'FULL'))
        else:
            try:
                query = text("SELECT MIN(time), MAX(time) FROM market_data_daily WHERE symbol = :symbol")
                with engine.connect() as conn:
                    res = conn.execute(query, {"symbol": ticker}).fetchone()
                    min_dt, max_dt = res if res else (None, None)
                
                if min_dt and max_dt:
                    min_dt, max_dt = pd.to_datetime(min_dt).replace(tzinfo=None), pd.to_datetime(max_dt).replace(tzinfo=None)
                    if target_start < min_dt - pd.Timedelta(days=1):
                        fetch_ranges.append((target_start, min_dt - pd.Timedelta(days=1), 'HEAD'))
                    
                    is_crypto = 'X:' in ticker
                    threshold = 0 if is_crypto else 1
                    if (target_end - max_dt).days > threshold:
                        fetch_ranges.append((max_dt + pd.Timedelta(days=1), target_end, 'TAIL'))
                else:
                    fetch_ranges.append((target_start, target_end, 'FULL'))

                if not fetch_ranges and min_dt and max_dt:
                    logger.success(f"Synchronized ({min_dt.date()} to {max_dt.date()}) for {ticker}.", tag="MARKET")
                    stats["success"] += 1
                    continue

            except Exception as e:
                logger.error(f"DB Check failed for {ticker}: {e}", tag="MARKET")
                fetch_ranges.append((target_start, target_end, 'FULL'))

        for s_dt, e_dt, gap_type in fetch_ranges:
            s_str, e_str = s_dt.strftime('%Y-%m-%d'), e_dt.strftime('%Y-%m-%d')
            two_years_ago = (MarketClock.now() - timedelta(days=720)).replace(tzinfo=None)
            use_yfinance = s_dt < two_years_ago
            
            # [IRONCLAD FIX] Adjustment Bridge: Validate cross-source consistency
            if use_yfinance and (MarketClock.now().replace(tzinfo=None) - s_dt).days < 800:
                # We are near the 2-year boundary, let's check a bridge window
                bridge_start = (two_years_ago - timedelta(days=5)).strftime('%Y-%m-%d')
                bridge_end = two_years_ago.strftime('%Y-%m-%d')
                try:
                    p_bridge = fetch_bars_with_retry(ticker, bridge_start, bridge_end, use_yfinance=False)
                    y_bridge = fetch_bars_with_retry(ticker, bridge_start, bridge_end, use_yfinance=True)
                    if not DataValidator.validate_adjustment_bridge(ticker, p_bridge, y_bridge):
                        logger.error(f"Bridge Validation Failed for {ticker}. Data may be inconsistent!", tag="MARKET")
                except Exception as b_err:
                    logger.warning(f"Bridge check failed for {ticker}: {b_err}", tag="MARKET")

            try:
                bars = fetch_bars_with_retry(ticker, s_str, e_str, use_yfinance=use_yfinance)
                
                if not bars:
                    if gap_type in ['HEAD', 'FULL']:
                        # [IRONCLAD FIX] Don't silence it forever if it's just a 'discovery' failure.
                        # We only mark it as 'synched' if we are sure it's a dead range (e.g. IPO date found).
                        logger.warning(f"Discovery: No data for {ticker} in {s_str}->{e_str}. Hole remains for later retry.", tag="MARKET")
                    continue

                valid_bars = validate_bars(bars, ticker)
                if not valid_bars: 
                    logger.warning(f"All {len(bars)} bars failed validation for {ticker}. Hole remains.", tag="MARKET")
                    continue
                
                df = pd.DataFrame(valid_bars)
                df['time'] = pd.to_datetime(df['timestamp'], unit='ms')
                df['symbol'] = ticker
                
                # [IRONCLAD FIX] Split Sentinel: Detect suspicious price jumps
                DataValidator.detect_vertical_jumps(df, ticker)
                
                data_to_store = df[['time', 'symbol', 'adj_open', 'adj_high', 'adj_low', 'adj_close', 'adj_volume', 'open', 'high', 'low', 'close', 'volume']].to_dict(orient='records')
                for record in data_to_store:
                    if hasattr(record['time'], 'to_pydatetime'):
                        record['time'] = record['time'].to_pydatetime()
                
                with engine.connect() as conn:
                    stmt = text("""
                        INSERT INTO market_data_daily (time, symbol, adj_open, adj_high, adj_low, adj_close, adj_volume, open, high, low, close, volume)
                        VALUES (:time, :symbol, :adj_open, :adj_high, :adj_low, :adj_close, :adj_volume, :open, :high, :low, :close, :volume)
                        ON CONFLICT (time, symbol) DO UPDATE SET
                        adj_open = EXCLUDED.adj_open, adj_high = EXCLUDED.adj_high, adj_low = EXCLUDED.adj_low,
                        adj_close = EXCLUDED.adj_close, adj_volume = EXCLUDED.adj_volume, open = EXCLUDED.open,
                        high = EXCLUDED.high, low = EXCLUDED.low, close = EXCLUDED.close, volume = EXCLUDED.volume;
                    """)
                    conn.execute(stmt, data_to_store)
                    conn.commit()
                
                logger.success(f"Saved {len(df)} rows for {ticker} ({gap_type}).", tag="MARKET")
                stats["success"] += 1
                stats["rows"] += len(df)
                
                # [IRONCLAD UPGRADE] Update sync_metadata ONLY after successful row insertion
                with engine.connect() as conn:
                    conn.execute(text("""
                        INSERT INTO sync_metadata (symbol, component, last_synced)
                        VALUES (:symbol, 'market_history', :now)
                        ON CONFLICT (symbol, component) DO UPDATE SET last_synced = EXCLUDED.last_synced
                    """), {"symbol": ticker, "now": MarketClock.now()})
                    conn.commit()
            except Exception as e:
                logger.error(f"Hard Failure for {ticker}: {e}", tag="MARKET")
                stats["failed"] += 1
            
            time.sleep(2) # Modest throttle for stability
    return stats


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--tickers', type=str, help='Comma separated tickers')
    args = parser.parse_args()
    
    # Initialize Universal Ingestion Logger for standalone runs
    logger.setup_ingestion_logging()
    
    if args.tickers:
        tickers = args.tickers.split(',')
    else:
        tickers = ModelConfig.TICKERS
    
    lookback_days = int(ModelConfig.DAILY_ML_TRAINING_WINDOW * ModelConfig.CALENDAR_TO_TRADING_SCALAR)
    start_dt = pd.Timestamp(ModelConfig.START_DATE) - pd.Timedelta(days=lookback_days)
    start_str = start_dt.strftime('%Y-%m-%d')
    end_str = ModelConfig.END_DATE
    
    logger.audit(f"Starting standalone Market Ingestion for {len(tickers)} symbols", tag="MARKET")
    ingest_market_data(tickers, start_str, end_str)
