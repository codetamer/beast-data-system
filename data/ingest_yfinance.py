import yfinance as yf
import pandas as pd
import numpy as np
import sys
import os
import time
from sqlalchemy import create_engine, text
from datetime import datetime, timedelta
import random

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import DB_URI
from config.model_config import ModelConfig
from utils.logger import logger
from utils.market_clock import MarketClock
from utils.networking import retry_with_backoff

def ingest_yfinance_fundamentals(tickers: list[str], start_date=None, end_date=None, force=False):
    """
    Ingests fundamental data from yfinance and maps it to the existing `fundamentals` schema.
    Metics: shares_outstanding, debt, book_value, net_income, eps, cfo, capex, 
             cash_equivalent, gross_profit, total_assets
    """
    engine = create_engine(DB_URI)
    stats = {"success": 0, "failed": 0, "rows": 0}
    
    logger.info(f"--- Starting yfinance Ingestion for {len(tickers)} symbols ---", tag="YFINANCE")
    
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

    @retry_with_backoff(tag="YFINANCE")
    def fetch_yt_data(ticker):
        yt = yf.Ticker(ticker)
        # Force a handshake to trigger 429 early if needed
        _ = yt.info
        return yt

    for ticker in tickers:
        if ticker.startswith('X:'): continue
        
        logger.info(f"Processing {ticker}...", tag="YFINANCE")
        try:
            needs_fetch = False
            if force:
                needs_fetch = True
            else:
                try:
                    check_range_q = "SELECT MIN(report_date), MAX(report_date) FROM fundamentals WHERE symbol = :symbol"
                    with engine.connect() as conn:
                        res = conn.execute(text(check_range_q), {"symbol": ticker}).fetchone()
                        min_rd, max_rd = res if res else (None, None)
                    
                    sync_q = "SELECT last_synced FROM sync_metadata WHERE symbol = :symbol AND component = 'fundamentals'"
                    with engine.connect() as conn:
                        sync_res = conn.execute(text(sync_q), {"symbol": ticker}).fetchone()
                        last_check = pd.to_datetime(sync_res[0]).replace(tzinfo=None) if sync_res and sync_res[0] else None
                    
                    target_start = pd.to_datetime(start_date).replace(tzinfo=None) if start_date else (MarketClock.now() - timedelta(days=ModelConfig.DAILY_ML_TRAINING_WINDOW + ModelConfig.STRUCTURAL_WARMUP_DAYS + 90)).replace(tzinfo=None)
                    target_end = pd.to_datetime(end_date).replace(tzinfo=None) if end_date else MarketClock.now().replace(tzinfo=None)
                    
                    if min_rd and max_rd:
                        min_rd, max_rd = pd.to_datetime(min_rd).replace(tzinfo=None), pd.to_datetime(max_rd).replace(tzinfo=None)
                        days_since_last_report = (MarketClock.now().replace(tzinfo=None) - max_rd).days
                        if min_rd > target_start:
                            needs_fetch = True
                        
                        is_stale = (target_end - max_rd).days >= 5 
                        if is_stale or days_since_last_report >= 85:
                            if last_check and (MarketClock.now().replace(tzinfo=None) - last_check).days < 3:
                                if not needs_fetch:
                                    logger.info(f"Recent Check ({last_check.date()}). Skipping {ticker}.", tag="YFINANCE")
                                    stats["success"] += 1
                                    continue
                            else:
                                needs_fetch = True
                    else:
                        needs_fetch = True
                except Exception as e:
                    logger.error(f"DB Check failed for {ticker}: {e}", tag="YFINANCE")
                    needs_fetch = True

            if not needs_fetch:
                with engine.connect() as conn:
                    conn.execute(text("""
                        INSERT INTO sync_metadata (symbol, component, last_synced)
                        VALUES (:symbol, 'fundamentals', :now)
                        ON CONFLICT (symbol, component) DO UPDATE SET last_synced = EXCLUDED.last_synced
                    """), {"symbol": ticker, "now": MarketClock.now()})
                    conn.commit()
                continue

            yt = fetch_yt_data(ticker)
            shares = yt.info.get('sharesOutstanding')
            datasets = [
                (yt.quarterly_balance_sheet, yt.quarterly_financials, yt.quarterly_cashflow, 'Q'),
                (yt.balance_sheet, yt.financials, yt.cashflow, 'FY')
            ]
            
            records = []
            for bs_df, is_df, cf_df, period_type in datasets:
                if bs_df.empty or is_df.empty: continue
                available_cols = bs_df.columns.intersection(is_df.columns)
                if not cf_df.empty: available_cols = available_cols.intersection(cf_df.columns)
                
                # Sort chronologically for sequential unit anomaly detection
                if not isinstance(available_cols, list):
                    available_cols = sorted(list(available_cols))
                else:
                    available_cols = sorted(available_cols)
                    
                prev_metrics = {}
                
                for col in available_cols:
                    report_date = col.strftime('%Y-%m-%d')
                    pub_date = (col + pd.Timedelta(days=45)).strftime('%Y-%m-%d')
                    
                    def get_val(df, keys, date_col):
                        for k in keys:
                            if k in df.index: return df.loc[k, date_col]
                        return np.nan

                    metrics = {
                        'debt': get_val(bs_df, ['Total Debt', 'Long Term Debt'], col),
                        'book_value': get_val(bs_df, ['Stockholders Equity', 'Total Stockholders Equity', 'Total Equity'], col),
                        'net_income': get_val(is_df, ['Net Income', 'Net Income Common Stockholders'], col),
                        'eps': get_val(is_df, ['Basic EPS', 'Diluted EPS'], col),
                        'revenue': get_val(is_df, ['Total Revenue', 'Operating Revenue'], col),
                        'cfo': get_val(cf_df, ['Operating Cash Flow', 'Cash Flow From Continuing Operating Activities', 'Net Cash From Operating Activities'], col),
                        'capex': get_val(cf_df, ['Capital Expenditure', 'Capital Expenditures', 'Purchase Of Property Plant And Equipment'], col),
                        'cash_equivalent': get_val(bs_df, ['Cash And Cash Equivalents', 'Cash Financial Assets', 'Cash'], col),
                        'gross_profit': get_val(is_df, ['Gross Profit'], col),
                        'total_assets': get_val(bs_df, ['Total Assets', 'Assets'], col),
                        'shares_outstanding': get_val(is_df, ['Basic Average Shares', 'Diluted Average Shares', 'Ordinary Shares Number'], col)
                    }

                    # [IRONCLAD FIX] Unit Sanitizer: Detect Millions/Billions scaling errors
                    for m in ['total_assets', 'revenue', 'book_value', 'shares_outstanding']:
                        if not pd.isna(metrics[m]) and metrics[m] < 0 and m != 'book_value':
                            metrics[m] = np.nan # Sanity: these shouldn't be negative in most cases

                    # Sequential Anomaly Guard (Fractional/Multiple Unit Errors)
                    # Vendors often mix thousands, millions, and billions scaling across quarters.
                    for m in ['total_assets', 'shares_outstanding', 'revenue', 'gross_profit']:
                        val = metrics[m]
                        if not pd.isna(val) and m in prev_metrics and prev_metrics[m] is not None:
                            prev_val = prev_metrics[m]
                            if abs(prev_val) > 1e-6:
                                ratio = val / prev_val
                                # Asset/Shares shouldn't jump 500% or drop 80% QoQ natively
                                if m in ['total_assets', 'shares_outstanding'] and (ratio > 5.0 or ratio < 0.2):
                                    logger.warning(f"Anomaly Sanitized: {ticker} {m} jumped {ratio:.1f}x ({prev_val} -> {val})", tag="SANITIZER")
                                    metrics[m] = np.nan
                                # Revenues/Profits fluctuate more, but 10x is generally a unit scaling bug 
                                elif m in ['revenue', 'gross_profit'] and (ratio > 10.0 or ratio < 0.1):
                                    logger.warning(f"Anomaly Sanitized: {ticker} {m} jumped {ratio:.1f}x ({prev_val} -> {val})", tag="SANITIZER")
                                    metrics[m] = np.nan
                                    
                    # Update previous tracker for next chronological iteration
                    for m in ['total_assets', 'shares_outstanding', 'revenue', 'gross_profit']:
                        if not pd.isna(metrics[m]):
                            prev_metrics[m] = metrics[m]

                    # Calculated metrics
                    if pd.isna(metrics['gross_profit']) and not pd.isna(metrics['revenue']):
                        cor = get_val(is_df, ['Cost Of Revenue'], col)
                        metrics['gross_profit'] = metrics['revenue'] - cor if not pd.isna(cor) else metrics['revenue']
                    
                    metrics['roe'] = np.nan
                    if not pd.isna(metrics['net_income']) and not pd.isna(metrics['book_value']) and abs(metrics['book_value']) > 1e-6:
                        metrics['roe'] = metrics['net_income'] / abs(metrics['book_value'])

                    # [IRONCLAD FIX] Dynamic Pub-Dates: Try to find actual filing date from DB
                    # If we already have SEC data for this date, use its pub_date.
                    try:
                        with engine.connect() as conn:
                            actual_filed = conn.execute(text(
                                "SELECT MIN(pub_date) FROM fundamentals WHERE symbol = :s AND report_date = :r AND pub_date IS NOT NULL"
                            ), {"s": ticker, "r": report_date}).scalar()
                            if actual_filed:
                                pub_date = pd.to_datetime(actual_filed).strftime('%Y-%m-%d')
                    except: pass

                    for m, val in metrics.items():
                        if not pd.isna(val):
                            records.append({
                                'report_date': report_date, 'pub_date': pub_date,
                                'symbol': ticker, 'metric': m, 'value': float(val), 'period': period_type
                            })
            
            if records:
                with engine.connect() as conn:
                    stmt = text("""
                        INSERT INTO fundamentals (report_date, pub_date, symbol, metric, value, period)
                        VALUES (:report_date, :pub_date, :symbol, :metric, :value, :period)
                        ON CONFLICT (report_date, symbol, metric) DO UPDATE SET
                        value = EXCLUDED.value, pub_date = EXCLUDED.pub_date, period = EXCLUDED.period;
                    """)
                    conn.execute(stmt, records)
                    conn.commit()
                logger.success(f"Saved {len(records)} records for {ticker}.", tag="YFINANCE")
                stats["success"] += 1
                stats["rows"] += len(records)
            else:
                logger.warning(f"Silent Discovery: No fundamentals for {ticker}. Marking as synched.", tag="YFINANCE")
                stats["success"] += 1

            with engine.connect() as conn:
                conn.execute(text("""
                    INSERT INTO sync_metadata (symbol, component, last_synced)
                    VALUES (:symbol, 'fundamentals', :now)
                    ON CONFLICT (symbol, component) DO UPDATE SET last_synced = EXCLUDED.last_synced
                """), {"symbol": ticker, "now": MarketClock.now()})
                conn.commit()
                
        except Exception as e:
            logger.error(f"Hard Failure for {ticker}: {e}", tag="YFINANCE")
            stats["failed"] += 1
        
        time.sleep(random.uniform(2, 5))
        
    logger.info("--- yfinance Ingestion Complete ---", tag="YFINANCE")
    return stats

if __name__ == "__main__":
    # Initialize Universal Ingestion Logger for standalone runs
    logger.setup_ingestion_logging()
    
    tickers = ModelConfig.STOCKS
    logger.audit(f"Starting standalone YFinance Ingestion for {len(tickers)} symbols", tag="YFINANCE")
    ingest_yfinance_fundamentals(tickers, force=False)
