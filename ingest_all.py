"""
Unified Data Ingestion Script for Beast Quant.
Orchestrates fetching of Market, Fundamental, Macro, and Intraday data.

Usage:
    python ingest_all.py --mode daily     (Run fast daily updates)
    python ingest_all.py --mode full      (Run EVERYTHING - heavy)
    python ingest_all.py --mode fundamentals  (Fetch fundamentals only)
"""
import sys
import os
import argparse
import pandas as pd
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add standalone root to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config.model_config import ModelConfig
from data.ingest_market import ingest_market_data
from data.ingest_yfinance import ingest_yfinance_fundamentals
from data.ingest_sec import ingest_sec_fundamentals
from data.ingest_macro import ingest_macro_data
from data.database_init import setup_database
from utils.logger import logger

def print_summary(report):
    logger.audit("BEAST QUANT - INGESTION SUMMARY", tag="INGEST")
    summary_data = {}
    for task, stats in report.items():
        s = stats.get('success', 0)
        f = stats.get('failed', 0)
        r = stats.get('rows', 0)
        summary_data[task] = f"S:{s} F:{f} R:{r}"
    logger.table(summary_data, title="Ingestion Report", headers=("Component", "Stats"))

def run_daily_update(custom_start=None, custom_end=None, force=False, custom_tickers=None):
    """Parallelized update for daily backtests or live: Market + Macro."""
    logger.info(">>> Initializing Parallel Daily Update...", tag="INGEST")

    base_end = custom_end if custom_end else ModelConfig.END_DATE
    base_start = custom_start if custom_start else ModelConfig.START_DATE
    
    lookback_days = int((ModelConfig.DAILY_ML_TRAINING_WINDOW + ModelConfig.STRUCTURAL_WARMUP_DAYS) * ModelConfig.CALENDAR_TO_TRADING_SCALAR)
    target_start_dt = pd.Timestamp(base_start) - pd.Timedelta(days=lookback_days)
    start_str = target_start_dt.strftime('%Y-%m-%d')
    end_str = base_end
    
    results = {}
    
    tickers_to_use = custom_tickers if custom_tickers else ModelConfig.TICKERS
    
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {
            executor.submit(ingest_macro_data, start_str, end_str, force=force): "Macro (VIX)",
            executor.submit(ingest_market_data, tickers_to_use, start_str, end_str, force=force): "Market (Daily)"
        }
        
        for future in as_completed(futures):
            task_name = futures[future]
            try:
                results[task_name] = future.result()
                logger.success(f"{task_name} Ingestion Completed.", tag="INGEST")
            except Exception as e:
                logger.error(f"{task_name} Failed: {e}", tag="INGEST")
                results[task_name] = {'success': 0, 'failed': 1, 'rows': 0}

    # 3. Fundamentals (Required for Quality Factor) - Run sequentially as it's more API intensive
    results['Fundamentals'] = run_fundamentals(force=force, start_date=start_str, end_date=end_str, custom_tickers=custom_tickers)
    
    # Flatten fundamental results for reporting
    report = {
        "Macro (VIX)": results.get("Macro (VIX)", {}),
        "Market (Daily)": results.get("Market (Daily)", {}),
        "Fundamentals (YF)": results['Fundamentals']['YF'],
        "Fundamentals (SEC)": results['Fundamentals']['SEC']
    }
    
    return report

def run_fundamentals(force=False, start_date=None, end_date=None, custom_tickers=None):
    """Heavy Fundamental Fetch (Stocks Only) - Powered by SEC + yfinance."""
    logger.info(">>> Running Fundamentals Update (SEC + yfinance)...", tag="INGEST")
    
    universe = custom_tickers if custom_tickers else ModelConfig.STOCKS
    yf_universe = custom_tickers if custom_tickers else ModelConfig.DAILY_STRATEGY_UNIVERSE
    
    base_end = end_date if end_date else ModelConfig.END_DATE
    base_start = start_date if start_date else ModelConfig.START_DATE
    
    lookback_days = int((ModelConfig.DAILY_ML_TRAINING_WINDOW + ModelConfig.STRUCTURAL_WARMUP_DAYS) * ModelConfig.CALENDAR_TO_TRADING_SCALAR)
    target_start_dt = pd.Timestamp(base_start) - pd.Timedelta(days=lookback_days)
    
    # 1. SEC Layer (History backfill)
    try:
        sec_stats = ingest_sec_fundamentals(universe, force=force)
    except Exception as e:
        logger.error(f"SEC Ingestion Failed: {e}", tag="INGEST")
        sec_stats = {'success': 0, 'failed': len(ModelConfig.STOCKS), 'rows': 0}

    # 2. yfinance Layer (Recent + ETFs)
    try:
        yf_stats = ingest_yfinance_fundamentals(yf_universe, 
                                               start_date=target_start_dt, 
                                               end_date=base_end,
                                               force=force)
    except Exception as e:
        logger.error(f"yfinance Ingestion Failed: {e}", tag="INGEST")
        yf_stats = {'success': 0, 'failed': len(yf_universe), 'rows': 0}
        
    return {"SEC": sec_stats, "YF": yf_stats}

def main():
    parser = argparse.ArgumentParser(description="Beast Quant Data Ingestion")
    parser.add_argument('--mode', type=str, choices=['daily', 'fundamentals', 'full', 'all'], 
                        default='daily', help='Ingestion Mode')
    parser.add_argument('--start-date', type=str, help='YYYY-MM-DD Start Date (Optional)')
    parser.add_argument('--end-date', type=str, help='YYYY-MM-DD End Date (Optional)')
    parser.add_argument('--force', action='store_true', help='Force re-ingestion (Ignore Sentinels)')
    parser.add_argument('--tickers', type=str, help='Comma-separated list of symbols (e.g. AAPL,TSLA)')
    
    args = parser.parse_args()
    
    report = {}
    start_time = time.time()

    # Initialize Universal Ingestion Logger
    logger.setup_ingestion_logging()
    
    # Auto-initialize database tables and indexes if database file is missing/cleared
    from config.settings import DB_URI
    from sqlalchemy import create_engine, text
    
    db_exists = False
    if DB_URI.startswith("sqlite:///"):
        db_path = DB_URI.replace("sqlite:///", "").replace("sqlite://", "")
        if db_path and db_path != ":memory:":
            db_exists = os.path.exists(db_path)
    else:
        try:
            engine = create_engine(DB_URI)
            with engine.connect() as conn:
                conn.execute(text("SELECT 1 FROM market_data_daily LIMIT 1"))
            db_exists = True
        except Exception:
            db_exists = False
            
    if not db_exists:
        logger.info("Database not present or uninitialized. Running schema creator...", tag="INGEST")
        setup_database()
    
    try:
        if args.mode == 'daily':
            ticker_list = args.tickers.split(',') if args.tickers else None
            report.update(run_daily_update(args.start_date, args.end_date, force=args.force, custom_tickers=ticker_list))
        elif args.mode == 'fundamentals':
            ticker_list = args.tickers.split(',') if args.tickers else None
            report.update(run_fundamentals(force=args.force, start_date=args.start_date, end_date=args.end_date, custom_tickers=ticker_list))
        elif args.mode in ['full', 'all']:
            report.update(run_daily_update(args.start_date, args.end_date, force=args.force))
            
        duration = time.time() - start_time
        print_summary(report)
        logger.info(f"Total Duration: {duration/60:.2f} minutes", tag="INGEST")

    except KeyboardInterrupt:
        logger.warning("Ingestion interrupted by user.", tag="INGEST")
        sys.exit(1)
    except Exception as e:
        logger.critical(f"Ingestion Failure: {e}", tag="INGEST")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        # AUTOMATED AUDITOR: Run post-ingestion integrity check
        try:
            from data.audit_db import audit_database
            logger.info(">>> Launching Automated Pipeline Auditor...", tag="AUDIT")
            audit_database()
            logger.success("Pipeline Audit Complete. Results logged to data/audit_report.txt", tag="AUDIT")
        except Exception as audit_err:
            logger.warning(f"Pipeline Auditor Failed: {audit_err}", tag="AUDIT")
        
if __name__ == "__main__":
    main()
