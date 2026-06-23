"""
===========================================================================
BEAST QUANT DATA INGESTION SYSTEM | STANDALONE LOAD DEMO
===========================================================================
This script demonstrates how to load pricing, fundamentals, and macro data
from the local SQLite/PostgreSQL database into Pandas structures for
analysis, backtesting, or visualization.

To run this demo:
1. Ensure dependencies are installed: pip install -r requirements.txt
2. Configure your .env file with the correct DB_URI
3. Initialize the database and run ingestion:
   python data/database_init.py
   python data/ingest_all.py --mode daily --tickers AAPL,MSFT
4. Run this script:
   python example_loader.py
===========================================================================
"""

import os
import sys
from dotenv import load_dotenv
import pandas as pd
from sqlalchemy import create_engine, text

# Load environment configuration (.env)
load_dotenv()

# Ensure local config and utils can be imported if run from this directory
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from data.loader import load_market_data, load_pivoted_fundamentals, load_macro_data
from config.settings import DB_URI
from utils.logger import logger

def run_loader_demo():
    logger.info("Starting Database Data Loading Demo...", tag="DEMO")
    
    # 1. Verify Database File/Connection
    engine = create_engine(DB_URI)
    logger.info(f"Database URI Target: {DB_URI}", tag="DEMO")
    
    # Check database counts
    try:
        with engine.connect() as conn:
            market_count = conn.execute(text("SELECT COUNT(*) FROM market_data_daily")).scalar()
            fund_count = conn.execute(text("SELECT COUNT(*) FROM fundamentals")).scalar()
            macro_count = conn.execute(text("SELECT COUNT(*) FROM macro_data")).scalar()
    except Exception as e:
        logger.error(f"Failed to connect to database: {e}", tag="DEMO")
        logger.warning("Please ensure you have renamed .env.example to .env and run database_init.py.", tag="DEMO")
        return

    logger.success("Connected to Database! Current Status:", tag="DEMO")
    print(f"   - daily market bars: {market_count} rows")
    print(f"   - fundamentals:      {fund_count} records")
    print(f"   - macro indicators:   {macro_count} rows\n")

    if market_count == 0:
        logger.warning("The database is currently empty.", tag="DEMO")
        logger.info("To populate it, run the ingestion orchestrator first:", tag="DEMO")
        print("   python data/ingest_all.py --mode daily --tickers AAPL,MSFT\n")
        return

    # 2. Loading Market Price Data
    logger.info("Loading Daily Market Data (OHLCV) for AAPL & MSFT...", tag="DEMO")
    try:
        prices_df = load_market_data(
            start_date="2020-01-01",
            end_date="2025-12-31",
            symbols=["AAPL", "MSFT"]
        )
        if not prices_df.empty:
            logger.success("Prices loaded successfully!", tag="DEMO")
            print(f"DataFrame Shape: {prices_df.shape}")
            print(prices_df.head(5))
            print("...\n")
        else:
            logger.warning("No price data found for the selected range/symbols.", tag="DEMO")
    except Exception as e:
        logger.error(f"Error loading price data: {e}", tag="DEMO")

    # 3. Loading Fundamental Statement Facts (Pivoted Point-in-Time)
    logger.info("Loading Pivoted PIT Fundamentals (net_income, revenue, total_assets)...", tag="DEMO")
    try:
        metrics = ["net_income", "revenue", "total_assets"]
        pivoted_dict = load_pivoted_fundamentals(
            start_date="2020-01-01",
            end_date="2025-12-31",
            symbols=["AAPL", "MSFT"],
            metrics=metrics
        )
        
        if pivoted_dict:
            for metric in metrics:
                metric_df = pivoted_dict.get(metric)
                if metric_df is not None and not metric_df.empty:
                    logger.success(f"Pivoted Fundamentals loaded for: {metric}", tag="DEMO")
                    print(metric_df.tail(4))
                    print("\n")
        else:
            logger.warning("No fundamentals data found.", tag="DEMO")
    except Exception as e:
        logger.error(f"Error loading fundamentals: {e}", tag="DEMO")

    # 4. Loading Macro Indicators
    logger.info("Loading Macro Indicators (VIX)...", tag="DEMO")
    try:
        vix_series = load_macro_data(
            start_date="2020-01-01",
            end_date="2025-12-31",
            metric="VIX"
        )
        if not vix_series.empty:
            logger.success("VIX macro index loaded successfully!", tag="DEMO")
            print(f"Series Length: {len(vix_series)} records")
            print(vix_series.tail(5))
            print("\n")
        else:
            logger.warning("No VIX macro data found.", tag="DEMO")
    except Exception as e:
        logger.error(f"Error loading macro data: {e}", tag="DEMO")

    logger.success("Demo finished successfully!", tag="DEMO")

if __name__ == "__main__":
    run_loader_demo()
