import sys
import os
import pandas as pd
from sqlalchemy import create_engine, text
from datetime import datetime

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import DB_URI
from config.model_config import ModelConfig
from utils.logger import logger
from utils.market_clock import MarketClock

def audit_database(report_path="data/audit_report.txt"):
    """
    Comprehensive Data Integrity Audit.
    Checks Market, Fundamental, and Macro data coverage against ModelConfig.
    """
    engine = create_engine(DB_URI)
    
    logger.audit("Starting Comprehensive Database Audit...", tag="AUDIT")
    
    full_report = []
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    full_report.append(f"BEAST QUANT DATA AUDIT - {timestamp}\n{'-'*50}\n")
    
    # --- 1. MARKET DATA AUDIT ---
    logger.info("Auditing Market Data (Daily)...", tag="AUDIT")
    tickers = ModelConfig.TICKERS
    market_stats = {}
    
    try:
        q = """
            SELECT symbol, MIN(time) as start_date, MAX(time) as end_date, COUNT(*) as count 
            FROM market_data_daily 
            GROUP BY symbol
        """
        df_market = pd.read_sql(q, engine)
        
        # Check coverage
        table_data = {}
        missing_tickers = []
        
        for t in tickers:
            row = df_market[df_market['symbol'] == t]
            if not row.empty:
                s_date = pd.to_datetime(row.iloc[0]['start_date']).date()
                e_date = pd.to_datetime(row.iloc[0]['end_date']).date()
                count = row.iloc[0]['count']
                
                # [IRONCLAD UPGRADE] Calculate Data Density
                # Expected trading days (roughly) using pandas bdate_range
                expected_days = len(pd.bdate_range(s_date, e_date))
                density = (count / expected_days * 100) if expected_days > 0 else 0
                
                market_stats[t] = {
                    "start": s_date, 
                    "end": e_date, 
                    "count": count,
                    "density": density
                }
                
                # Check for recency and density
                days_lag = (datetime.now().date() - e_date).days
                recency_status = "✅" if days_lag <= 5 else f"⚠️ ({days_lag}d lag)"
                density_status = "✅" if density >= 95 else f"❌ ({density:.1f}%)"
                
                table_data[t] = f"{s_date} -> {e_date} | {count:>4} rows | D:{density_status} | R:{recency_status}"
            else:
                market_stats[t] = {"start": None, "end": None, "count": 0, "density": 0}
                missing_tickers.append(t)
                table_data[t] = "❌ NO DATA"
        
        # Display Market Summary
        logger.table(table_data, title="Market Data Coverage", headers=("Symbol", "Range | Count | Status"))
        
        full_report.append("\n[MARKET DATA]")
        if missing_tickers:
            full_report.append(f"MISSING SYMBOLS: {', '.join(missing_tickers)}")
        else:
            full_report.append("All Config Tickers Present.")
            
        for t, stats in market_stats.items():
            density_str = f"{stats['density']:.1f}%" if stats['density'] > 0 else "N/A"
            full_report.append(f"{t:<10}: {stats['start']} to {stats['end']} | Rows: {stats['count']:>4} | Density: {density_str}")
            
    except Exception as e:
        logger.error(f"Market audit failed: {e}", tag="AUDIT")
        full_report.append(f"Market Audit Error: {e}")

    # --- 2. FUNDAMENTAL DATA AUDIT ---
    logger.info("Auditing Fundamental Data...", tag="AUDIT")
    stocks = ModelConfig.STOCKS
    fund_stats = {}
    
    try:
        # Check metric counts per symbol
        q = """
            SELECT symbol, metric, COUNT(*) as count 
            FROM fundamentals 
            GROUP BY symbol, metric
        """
        df_fund = pd.read_sql(q, engine)
        
        key_metrics = ['net_income', 'revenue', 'total_assets', 'cfo', 'shares_outstanding']
        fund_table = {}
        
        for s in stocks:
            s_metrics = df_fund[df_fund['symbol'] == s]
            if not s_metrics.empty:
                present_metrics = s_metrics['metric'].unique()
                missing_keys = [m for m in key_metrics if m not in present_metrics]
                
                total_reports = s_metrics['count'].sum()
                status = "✅" if not missing_keys else f"⚠️ (-{len(missing_keys)})"
                fund_table[s] = f"{len(present_metrics)} Metrics | {total_reports:>3} Records {status}"
                
                fund_stats[s] = {
                    "metrics_count": len(present_metrics),
                    "total_records": total_reports,
                    "missing_key_metrics": missing_keys
                }
            else:
                fund_table[s] = "❌ NO DATA"
                fund_stats[s] = {"metrics_count": 0, "total_records": 0, "missing_key_metrics": key_metrics}
        
        logger.table(fund_table, title="Fundamental Coverage", headers=("Symbol", "Metrics | Records | Status"))
        
        full_report.append("\n[FUNDAMENTAL DATA]")
        for s, stats in fund_stats.items():
            missing_str = f"Missing: {stats['missing_key_metrics']}" if stats['missing_key_metrics'] else "Complete"
            full_report.append(f"{s:<10}: {stats['metrics_count']} metrics, {stats['total_records']} records. {missing_str}")

    except Exception as e:
        logger.error(f"Fundamental audit failed: {e}", tag="AUDIT")
        full_report.append(f"Fundamental Audit Error: {e}")

    # --- 3. MACRO DATA AUDIT ---
    logger.info("Auditing Macro Data...", tag="AUDIT")
    try:
        q = "SELECT metric, MIN(time) as min, MAX(time) as max, COUNT(*) as count FROM macro_data GROUP BY metric"
        df_macro = pd.read_sql(q, engine)
        
        macro_table = {}
        if not df_macro.empty:
            full_report.append("\n[MACRO DATA]")
            for _, row in df_macro.iterrows():
                m = row['metric']
                s = pd.to_datetime(row['min']).date()
                e = pd.to_datetime(row['max']).date()
                c = row['count']
                macro_table[m] = f"{s} -> {e} ({c} rows)"
                full_report.append(f"{m:<10}: {s} to {e} ({c} rows)")
        else:
            macro_table["MACRO"] = "❌ NO DATA"
            full_report.append("No Macro Data Found.")
            
        logger.table(macro_table, title="Macro Data", headers=("Metric", "Range (Count)"))
        
    except Exception as e:
        logger.error(f"Macro audit failed: {e}", tag="AUDIT")
        full_report.append(f"Macro Audit Error: {e}")

    # --- Write Full Report ---
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(full_report))
    
    logger.success(f"Audit Complete. Full report saved to {report_path}", tag="AUDIT")

if __name__ == "__main__":
    # Initialize logger for standalone run
    logger.setup_ingestion_logging()
    audit_database()
