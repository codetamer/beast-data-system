import os
from dotenv import load_dotenv
import sqlite3
import datetime

# Register standard datetime adapters for Python 3.12+ / sqlite3
sqlite3.register_adapter(datetime.datetime, lambda dt: dt.strftime('%Y-%m-%d %H:%M:%S'))
sqlite3.register_adapter(datetime.date, lambda d: d.strftime('%Y-%m-%d'))

try:
    import pandas as pd
    sqlite3.register_adapter(pd.Timestamp, lambda ts: ts.strftime('%Y-%m-%d %H:%M:%S'))
except ImportError:
    pass

# Load .env file
load_dotenv()

# Database Config
DB_URI = os.getenv("DB_URI")
if DB_URI and DB_URI.startswith("sqlite:///"):
    if not DB_URI.startswith("sqlite:////"):
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        rel_path = DB_URI[10:]
        abs_path = os.path.abspath(os.path.join(project_root, rel_path))
        DB_URI = f"sqlite:///{abs_path}"
elif not DB_URI:
    # Default to SQLite local database
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_path = os.path.join(project_root, "data", "quant.db")
    DB_URI = f"sqlite:///{db_path}"

# Polygon.io Config
POLYGON_API_KEY = os.getenv("POLYGON_API_KEY", "YOUR_API_KEY")




