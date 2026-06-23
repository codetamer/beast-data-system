import sys
import os
from sqlalchemy import create_engine, text

# Add project root
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import DB_URI

def setup_database():
    """
    Unified database initialization.
    Creates all necessary tables and converts them to TimescaleDB hypertables if not on SQLite.
    """
    # Ensure parent directory for SQLite database exists
    if DB_URI.startswith("sqlite:///"):
        db_path = DB_URI.replace("sqlite:///", "").replace("sqlite://", "")
        if db_path and db_path != ":memory:":
            db_dir = os.path.dirname(db_path)
            if db_dir:
                os.makedirs(db_dir, exist_ok=True)

    engine = create_engine(DB_URI)
    is_sqlite = engine.dialect.name == "sqlite"
    
    with engine.connect() as conn:
        print("\n--- Initializing Beast Quant Database ---")
        
        # 1. Daily Market Data
        print("Verifying market_data_daily...")
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS market_data_daily (
                time TIMESTAMP NOT NULL,
                symbol TEXT NOT NULL,
                open DOUBLE PRECISION,
                high DOUBLE PRECISION,
                low DOUBLE PRECISION,
                close DOUBLE PRECISION,
                volume DOUBLE PRECISION,
                adj_open DOUBLE PRECISION,
                adj_high DOUBLE PRECISION,
                adj_low DOUBLE PRECISION,
                adj_close DOUBLE PRECISION,
                adj_volume DOUBLE PRECISION,
                PRIMARY KEY (time, symbol)
            );
        """))
        if not is_sqlite:
            try:
                conn.execute(text("SELECT create_hypertable('market_data_daily', 'time', if_not_exists => TRUE);"))
            except Exception: 
                conn.rollback() 
        conn.commit()

        # 3. Fundamentals (PIT)
        print("Verifying fundamentals...")
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS fundamentals (
                report_date DATE NOT NULL,
                pub_date DATE NOT NULL,
                symbol TEXT NOT NULL,
                metric TEXT NOT NULL,
                value DOUBLE PRECISION,
                period TEXT,
                PRIMARY KEY (report_date, symbol, metric)
            );
        """))
        conn.commit()
        
        # 4. Macro Data
        print("Verifying macro_data...")
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS macro_data (
                time TIMESTAMP NOT NULL,
                metric TEXT NOT NULL,
                value DOUBLE PRECISION,
                PRIMARY KEY (time, metric)
            );
        """))
        conn.commit()
        if not is_sqlite:
            try:
                conn.execute(text("SELECT create_hypertable('macro_data', 'time', if_not_exists => TRUE);"))
            except Exception: 
                conn.rollback()
            conn.commit()

        # 5. Sync Metadata
        print("Verifying sync_metadata...")
        conn.execute(text("""
            CREATE TABLE IF NOT EXISTS sync_metadata (
                symbol TEXT NOT NULL, 
                component TEXT NOT NULL, 
                last_synced TIMESTAMP, 
                PRIMARY KEY (symbol, component)
            );
        """))
        conn.commit()
        
        # 6. Optimization (Indexes)
        print("Verifying Performance Indexes...")
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_daily_sym_time ON market_data_daily (symbol, time DESC);"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_fund_pub_sym ON fundamentals (pub_date, symbol);"))
        conn.execute(text("CREATE INDEX IF NOT EXISTS idx_fund_sym_metric ON fundamentals (symbol, metric);"))
        
        conn.commit()
        print("--- Database Initialization Complete ---\n")

if __name__ == "__main__":
    setup_database()
