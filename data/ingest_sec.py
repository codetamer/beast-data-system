import requests
import pandas as pd
import sys
import os
import time
from sqlalchemy import create_engine, text

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.settings import DB_URI
from config.model_config import ModelConfig
from utils.logger import logger

# SEC requires a descriptive User-Agent (Company Name & Contact Email)
USER_AGENT = os.getenv("SEC_USER_AGENT", "BeastQuant Research (your-email@example.com)")
HEADERS = {"User-Agent": USER_AGENT}

class SECCollector:
    def __init__(self):
        self.engine = create_engine(DB_URI)
        self.session = self._init_session()
        self.cik_map = self._load_cik_map()
        
    def _init_session(self):
        """Initialize a robust session with retry logic."""
        session = requests.Session()
        session.headers.update(HEADERS)
        # Retry Strategy: 3 retries, exponential backoff (0.5s, 1s, 2s)
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["HEAD", "GET", "OPTIONS"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def _load_cik_map(self) -> dict:
        """Fetch official Ticker-to-CIK mapping from SEC."""
        url = "https://www.sec.gov/files/company_tickers.json"
        try:
            resp = self.session.get(url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            # Format: {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...}
            return {v['ticker']: str(v['cik_str']).zfill(10) for k, v in data.items()}
        except Exception as e:
            logger.error(f"Failed to load SEC CIK map: {e}", tag="SEC")
            return {}

    def fetch_company_facts(self, ticker: str):
        """Fetch all historical facts for a given ticker."""
        cik = self.cik_map.get(ticker.upper())
        if not cik:
            logger.warning(f"No CIK found for {ticker}", tag="SEC")
            return None
            
        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        try:
            # Session handles retries
            resp = self.session.get(url, timeout=15)
            if resp.status_code == 404:
                logger.warning(f"No SEC Facts API data for {ticker} (CIK {cik})", tag="SEC")
                return None
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"SEC API Error for {ticker}: {e}", tag="SEC")
            return None

    def parse_and_store(self, ticker: str, data: dict):
        """Map XBRL tags to DB schema and store."""
        if not data or 'facts' not in data:
            return 0
            
        us_gaap = data['facts'].get('us-gaap', {})
        ifrs = data['facts'].get('ifrs-full', {})
        dei = data['facts'].get('dei', {})
        
        if not us_gaap and not ifrs and not dei:
            return 0
            
        # Target Metrics Mapping
        # Priority tags for each of our target metrics (Standard US-GAAP and IFRS equivalents)
        TAGS_MAP = {
            'net_income': [
                'NetIncomeLoss', 
                'NetIncomeLossAvailableToCommonStockholdersBasic', 
                'ProfitLoss'
            ],
            'revenue': [
                'Revenues',
                'SalesRevenueNet',
                'SalesRevenueGoodsNet',
                'RevenueFromContractWithCustomerExcludingAssessedTax'
            ],
            'book_value': [
                'StockholdersEquity', 
                'Equity', 
                'EquityAttributableToOwnersOfParent'
            ],
            'debt': [
                'LongTermDebt', 
                'LongTermDebtNoncurrent', 
                'ShortTermBorrowings', 
                'Borrowings'
            ],
            'shares_outstanding': [
                'WeightedAverageNumberOfSharesOutstandingBasic',
                'WeightedAverageNumberOfSharesOutstandingDiluted',
                'EntityCommonStockSharesOutstanding', 
                'CommonStockSharesOutstanding', 
                'CommonStockSharesIssued'
            ],
            'cfo': [
                'NetCashProvidedByUsedInOperatingActivities',
                'CashFlowsProvidedByUsedInOperatingActivities',
                'NetCashProvidedByUsedInOperatingActivitiesContinuingOperations'
            ],
            'capex': [
                'PaymentsToAcquireProductiveAssets',
                'PaymentsToAcquirePropertyPlantAndEquipment',
                'PaymentsToAcquirePropertyPlantAndEquipmentAndIntangibleAssets'
            ],
            'cash_equivalent': [
                'CashAndCashEquivalentsAtCarryingValue',
                'CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents',
                'Cash'
            ],
            'gross_profit': [
                'GrossProfit',
                'GrossMargin'
            ],
            'total_assets': [
                'Assets'
            ]
        }
        
        records = []
        
        # 1. First Pass: Extract all raw metrics available
        raw_values = {} # (report_date, period) -> {metric: val}
        
        for target_metric, xbrl_tags in TAGS_MAP.items():
            for tag in xbrl_tags:
                fact_data = us_gaap.get(tag) or ifrs.get(tag) or dei.get(tag)
                if not fact_data or 'units' not in fact_data:
                    continue
                
                unit = 'USD' if 'USD' in fact_data['units'] else list(fact_data['units'].keys())[0] if fact_data['units'] else None
                if not unit: continue
                
                for entry in fact_data['units'][unit]:
                    form = entry.get('form')
                    if form not in ['10-K', '10-Q']:
                        continue
                        
                    report_date = entry['end']
                    filed_date = entry['filed']
                    val = entry['val']
                    period = 'FY' if form == '10-K' else 'Q'
                    
                    key = (report_date, period)
                    if key not in raw_values: raw_values[key] = {'pub_date': filed_date}
                    raw_values[key][target_metric] = float(val)
                
                # Move to next target_metric
                break

        # 2. Second Pass: Calculate Ratios (ROE) and apply fallbacks
        for (report_date, period), metrics in raw_values.items():
            pub_date = metrics.get('pub_date')
            
            # --- CALCULATED ROE ---
            ni = metrics.get('net_income')
            bv = metrics.get('book_value')
            if ni is not None and bv is not None and abs(bv) > 1e-6:
                metrics['roe'] = ni / abs(bv)

            # --- FALLBACK GROSS PROFIT ---
            gp = metrics.get('gross_profit')
            rev = metrics.get('revenue')
            if gp is None and rev is not None:
                # We don't have COGS in SEC easily without more tags, 
                # but for companies with no GP reported, Rev is often a safe proxy for top-line.
                metrics['gross_profit'] = rev

            # Convert to storage format
            for m, val in metrics.items():
                if m == 'pub_date': continue
                records.append({
                    'report_date': report_date,
                    'pub_date': pub_date,
                    'symbol': ticker,
                    'metric': m,
                    'value': float(val),
                    'period': period
                })
        
        if not records:
            return 0
            
        # Deduplicate and UPSERT
        # Sort by pub_date ascending so drop_duplicates(keep='last') keeps the newest amendment
        df_rec = pd.DataFrame(records).sort_values('pub_date').drop_duplicates(subset=['report_date', 'symbol', 'metric'], keep='last')
        
        try:
            with self.engine.connect() as conn:
                stmt = text("""
                    INSERT INTO fundamentals (report_date, pub_date, symbol, metric, value, period)
                    VALUES (:report_date, :pub_date, :symbol, :metric, :value, :period)
                    ON CONFLICT (report_date, symbol, metric) DO UPDATE SET
                        value = EXCLUDED.value,
                        pub_date = EXCLUDED.pub_date,
                        period = EXCLUDED.period;
                """)
                conn.execute(stmt, df_rec.to_dict(orient='records'))
                conn.commit()
            return len(df_rec)
        except Exception as e:
            logger.error(f"DB Error for {ticker}: {e}", tag="SEC")
            return 0

def ingest_sec_fundamentals(tickers: list[str], force=False):
    """Orchestrator for SEC Ingestion."""
    logger.info(f"--- Starting SEC EDGAR Ingestion for {len(tickers)} symbols ---", tag="SEC")
    collector = SECCollector()
    stats = {"success": 0, "failed": 0, "rows": 0}
    
    for ticker in tickers:
        # Skip Crypto and ETFs
        if ticker.startswith('X:') or ticker in ModelConfig.ETFS:
            continue
            
        logger.info(f"Processing SEC: {ticker}...", tag="SEC")
        
        # Check if we already have deep history (2018-2021)
        if not force:
            check_q = text("SELECT COUNT(*) FROM fundamentals WHERE symbol = :symbol AND report_date < '2022-01-01'")
            with collector.engine.connect() as conn:
                count = conn.execute(check_q, {"symbol": ticker}).scalar()
            
            if count > 8: # Roughly 2 years of quarters
                logger.success(f"Deep History already present for {ticker}. Skipping SEC.", tag="SEC")
                stats["success"] += 1
                continue
        
        data = collector.fetch_company_facts(ticker)
        if data:
            rows = collector.parse_and_store(ticker, data)
            if rows > 0:
                print(f"  🚀 SEC Ingested {rows} records for {ticker}.")
                stats["success"] += 1
                stats["rows"] += rows
            else:
                print(f"  ⚠️ No valid facts extracted for {ticker}.")
                stats["success"] += 1
        else:
            stats["failed"] += 1
            
        # SEC rate limit is 10 requests per second. We are being generous here.
        time.sleep(0.2)
        
    logger.info(f"--- SEC Ingestion Complete ---", tag="SEC")
    return stats

if __name__ == "__main__":
    ingest_sec_fundamentals(ModelConfig.STOCKS)
