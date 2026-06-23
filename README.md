# 💾 Beast Quant Data Ingestion System

An institutional-grade, multi-source financial data ingestion engine designed to build and maintain a local database for quantitative backtesting, alpha research, and systematic trading models.

This standalone package fetches daily price history, point-in-time fundamentals, and global macro indicators from multiple reliable providers, sanitizing and storing them in a standardized, query-optimized relational schema.

---

## 📊 The Quant Advantage (Why This is Crucial for Quants)

In quantitative research, raw data from single APIs is often riddled with lookahead bias, split discrepancies, and unit scaling bugs. This system is designed specifically to mitigate these institutional pain points:

1.  **Lookahead Bias Elimination (Point-in-Time Fundamentals)**:
    *   *The Problem*: Standard fundamental databases index financials by the fiscal period end date (e.g. `2024-12-31`). However, companies only publish these statements weeks later during filings. Backtesting on the end date introduces **lookahead bias**, generating unrealistically high simulation returns.
    *   *The Advantage*: This pipeline scrapes raw SEC EDGAR XBRL filings to track both the reporting date and the **actual publication date (`pub_date`)**. The data loader loads metrics by publication date, ensuring your models only backtest with information legally public at that time.
2.  **Hybrid Sourcing Cost Optimization**:
    *   *The Problem*: Premium feeds (like Polygon) are highly accurate but limit historical lookup on basic plans. Yahoo Finance offers deep histories but has rate limits.
    *   *The Advantage*: The engine automatically fetches recent high-fidelity bars from Polygon and seamlessly bridges historical gaps (older than 2 years) using Yahoo Finance, saving substantial API subscription fees.
3.  **Automated Integrity Guards**:
    *   *Unit Sanitizer*: Automatically flags and corrects scaling discrepancies (such as vendor reports swapping between thousands, millions, or billions between quarters).
    *   *Adjustment Bridge*: Cross-validates split and dividend adjustment ratios between Polygon and Yahoo Finance to detect discrepancies before data corruption enters your database.
    *   *Split Sentinel*: Monitors incoming time series for unannounced corporate splits or abnormal price moves (>30% jumps).
4.  **Database Portability**:
    *   Runs on zero-config SQLite by default for simple local research, but the database initializer automatically handles migration to **TimescaleDB** (time-series optimized PostgreSQL) tables and hypertables if a Postgres connection is provided in your `.env`.

---

## 🌟 Key Features

*   **Multi-Source Data Fusion**:
    *   **Polygon.io**: High-fidelity, split-and-dividend-adjusted US equity/ETF/Crypto data (primary provider).
    *   **SEC EDGAR**: Standardized Point-in-Time (PIT) fundamentals scraped directly from official XBRL SEC filings.
    *   **Yahoo Finance (yfinance)**: Fallback provider for deep historical data, index tickers (VIX/DXY), and recent fundamental disclosures.
*   **Production-Grade Reliability & Guards**:
    *   **Sync Sentinel (Delta Updates)**: Automatically checks existing database coverage and only requests data for missing gaps (historical "HEAD" gaps or recent "TAIL" updates), significantly reducing API usage.
    *   **Adjustment Bridge**: Cross-validates split/dividend adjustment factors between Polygon and Yahoo Finance to detect and alert on data corruption risks.
    *   **Split Sentinel**: Inspects incoming price series for unannounced splits or abnormal price movements (>30% daily change).
    *   **Unit Sanitizer**: Detects and sanitizes vendor unit errors (mixed scaling between thousands/millions/billions in fundamental reports) and sequential QoQ anomalies.
    *   **Universal Sentinel Logger**: Outputs clean, standardized, ANSI-colored logs to console and archives plain-text traces in `/data/beast_ingestion.log`.
    *   **Pipeline Auditor**: Automatically runs a post-ingestion audit checking data density, lags, and completeness, saving results in `data/audit_report.txt`.

---

## 📂 System Layout

```
data/ingestion_system/
├── config/
│   ├── model_config.py      # Target asset lists (Stocks, ETFs, Cryptos)
│   └── settings.py          # Database URI and basic time zone adapters
├── data/
│   ├── __init__.py
│   ├── database_init.py     # Schema creator (SQLite or TimescaleDB)
│   ├── polygon_client.py    # Custom REST client for Polygon.io
│   ├── loader.py            # API layer to load data into Pandas
│   ├── validator.py         # Adjustment bridge and anomaly checkers
│   ├── ingest_market.py     # Aggregator for OHLCV data
│   ├── ingest_yfinance.py   # Aggregator for yfinance fundamentals
│   ├── ingest_sec.py        # SEC EDGAR filings facts harvester
│   ├── ingest_macro.py      # Macro metrics (VIX, DXY) collector
│   └── audit_db.py          # Database integrity and coverage auditor
├── .env.example             # Configuration file template
├── requirements.txt         # Minimal dependency list
├── example_loader.py        # Elegant, runnable data loading demo
├── ingest_all.py            # Orchestration layer (CLI interface)
└── README.md                # This Guide
```

---

## 🛠️ Installation & Setup

### 1. Install Dependencies

Ensure Python 3.10+ is installed. Install the required libraries:

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

Copy the environment template and name it `.env`:

```bash
cp .env.example .env
```

Open `.env` and fill in your details:

```env
# Connection string (defaults to a SQLite database in the 'data' directory)
DB_URI=sqlite:///data/quant.db

# Fill in your key from https://polygon.io/
POLYGON_API_KEY=YOUR_POLYGON_API_KEY_HERE
```

### 3. Customize Target Assets

The tickers to ingest are managed in `config/model_config.py`. Under the `ModelConfig` class, you can customize:
*   `ModelConfig.STOCKS`: List of corporate equities to ingest (e.g. `AAPL`, `MSFT`).
*   `ModelConfig.ETFS`: List of ETFs to ingest (e.g. `GLD`, `USO`).
*   `ModelConfig.CRYPTO`: List of cryptocurrency pairs (e.g. `X:BTCUSD`, `X:ETHUSD`).

---

## 🚀 Running the Pipeline

The pipeline is orchestrated from the main script `ingest_all.py` in the root of the `ingestion_system` folder.

> [!TIP]
> **Automatic Schema Initialization**: On your very first run, `ingest_all.py` will automatically check if the database is present and initialize the tables and performance indexes dynamically. There is no need to run separate setup scripts.

### Running Ingestion Modes

#### A. Daily Synchronization (Recommended)
Syncs recent price data (up to yesterday), macro indices, and updates fundamentals. This is fast as it uses the delta sync engine:

```bash
python ingest_all.py --mode daily
```

#### B. Full Reload / Historical Backfill
Pulls entire historical records (defined by `ModelConfig.START_DATE` to `ModelConfig.END_DATE`) forcing re-fetch (bypassing the cache sentinels):

```bash
python ingest_all.py --mode full --force
```

#### C. Custom Tick List & Date Ranges
You can target a specific list of tickers or overwrite the start/end dates:

```bash
python ingest_all.py --mode daily --tickers TSLA,NVDA --start-date 2024-01-01 --end-date 2024-12-31
```

#### D. Fetch Fundamentals Only
Only fetch fundamentals (from SEC EDGAR and yfinance) for the stocks universe:

```bash
python ingest_all.py --mode fundamentals
```

### 3. Inspect Ingestion Quality
The pipeline automatically runs an auditor after running `ingest_all.py`. You can also trigger it manually to inspect data coverage, density, and sync lags:

```bash
python data/audit_db.py
```

Check the detailed metrics report generated at `data/audit_report.txt`.

---

## 📊 Database Schema Details

By default, the SQLite database will be created at `data/quant.db`. It contains the following tables:

### 1. `market_data_daily`
Stores adjusted and unadjusted daily price bars for stocks, ETFs, and cryptocurrencies.

| Column | Type | Description |
| :--- | :--- | :--- |
| **time** (PK) | TIMESTAMP | Midnight timestamp in US/Eastern |
| **symbol** (PK) | TEXT | The asset symbol (e.g. `AAPL`, `X:BTCUSD`) |
| **open** | DOUBLE | Raw/unadjusted open price |
| **high** | DOUBLE | Raw/unadjusted high price |
| **low** | DOUBLE | Raw/unadjusted low price |
| **close** | DOUBLE | Raw/unadjusted close price |
| **volume** | DOUBLE | Raw/unadjusted volume |
| **adj_open** | DOUBLE | Split and dividend adjusted open price |
| **adj_high** | DOUBLE | Split and dividend adjusted high price |
| **adj_low** | DOUBLE | Split and dividend adjusted low price |
| **adj_close** | DOUBLE | Split and dividend adjusted close price |
| **adj_volume**| DOUBLE | Split and dividend adjusted volume |

### 2. `fundamentals`
Contains Point-in-Time (PIT) financial statement items.

| Column | Type | Description |
| :--- | :--- | :--- |
| **report_date** (PK)| DATE | Financial period ending date (e.g., `2024-03-31`) |
| **symbol** (PK) | TEXT | The corporate symbol (e.g., `MSFT`) |
| **metric** (PK) | TEXT | Metric identifier (e.g., `net_income`, `revenue`, `roe`) |
| **pub_date** | DATE | Publication/Filing date (safe for backtests to avoid lookahead bias) |
| **value** | DOUBLE | Numeric value of the metric |
| **period** | TEXT | Reporting frequency: `Q` (Quarterly) or `FY` (Fiscal Year) |

*Key metrics captured: `shares_outstanding`, `debt`, `book_value`, `net_income`, `eps`, `cfo` (operating cash flow), `capex`, `cash_equivalent`, `gross_profit`, `total_assets`, `roe` (return on equity).*

### 3. `macro_data`
Contains macro-regime time series data.

| Column | Type | Description |
| :--- | :--- | :--- |
| **time** (PK) | TIMESTAMP | Event date |
| **metric** (PK) | TEXT | Metric name (e.g., `VIX` or `DXY`) |
| **value** | DOUBLE | Value of the macro metric |

---

## 💻 How to Use the Fetched Data in Python

A pre-configured loading demo script [example_loader.py](example_loader.py) is provided in the root directory. It connects to the database, queries pricing, fundamentals, and macro indicators, and outputs clean previews. You can run it directly:

```bash
python example_loader.py
```

Alternatively, you can import the data loader module (`data/loader.py`) programmatically into your own scripts:

### Example 1: Loading Price Series
```python
import sys
import os

# Append paths if running outside the folder
sys.path.append(os.path.abspath('.'))

from data.loader import load_market_data

# Load adjusted prices for custom assets
df = load_market_data(
    start_date="2023-01-01", 
    end_date="2023-12-31", 
    symbols=["AAPL", "MSFT"]
)

print(df.head())
# Output is indexed by [time, symbol] with columns:
# open, high, low, close, volume (returns adjusted prices by default)
```

### Example 2: Loading Point-in-Time Fundamentals
```python
from data.loader import load_pivoted_fundamentals

# Load and pivot key metrics (returns dictionary of DataFrames)
metrics = ["net_income", "total_assets", "book_value"]
pivoted_data = load_pivoted_fundamentals(
    start_date="2020-01-01",
    end_date="2025-12-31",
    symbols=["AAPL", "MSFT", "GOOGL"],
    metrics=metrics
)

# Access Net Income dataframe (index=publication_date, columns=symbols)
net_income_df = pivoted_data.get("net_income")
print(net_income_df.tail())
```

### Example 3: Loading Macro Risk Indicators
```python
from data.loader import load_macro_data

# Fetch historical VIX series
vix_series = load_macro_data(
    start_date="2023-01-01",
    end_date="2023-12-31",
    metric="VIX"
)

print(vix_series.tail())
```

---

## 🏛️ License
Provided under the MIT License. Feel free to copy, modify, and distribute this data ingestion engine for personal or institutional use. Contribution pull requests are welcome!
