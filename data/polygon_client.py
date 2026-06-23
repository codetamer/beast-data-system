import logging
import time
from typing import List, Dict, Any, Optional
from polygon import RESTClient
from requests.exceptions import HTTPError
from config.settings import POLYGON_API_KEY

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class PolygonWrapper:
    def __init__(self, api_key: str = POLYGON_API_KEY):
        self.client = RESTClient(api_key)

    def get_aggs(self, ticker: str, multiplier: int, timespan: str, from_: str, to: str, adjusted: bool = True) -> List[Dict[str, Any]]:
        """
        Fetch aggregated bars (OHLCV).
        Handles pagination internally, but adding manual retry logic for 429s.
        """
        max_retries = 5
        backoff = 12 # Higher initial backoff to clear rate limit buckets (12s = 5/min tier safe)
        
        for attempt in range(max_retries):
            try:
                aggs = []
                # list_aggs is a generator, so we iterate to trigger requests
                for a in self.client.list_aggs(ticker, multiplier, timespan, from_, to, limit=50000, adjusted=adjusted):
                    aggs.append({
                        "timestamp": a.timestamp,
                        "open": a.open,
                        "high": a.high,
                        "low": a.low,
                        "close": a.close,
                        "volume": a.volume,
                        "vwap": a.vwap
                    })
                return aggs
                
            except Exception as e:
                err_str = str(e).lower()
                if "429" in err_str or "too many" in err_str:
                    wait_time = backoff * (2 ** attempt)
                    logger.warning(f"Rate Limit (429) hit for {ticker}. Waiting {wait_time}s...")
                    time.sleep(wait_time)
                else:
                    # Critical Error (Auth, Validation, etc) - Re-raise to trigger Fallback
                    logger.error(f"Error fetching aggs for {ticker}: {e}")
                    raise e
                    
        # If we exhaust retries (Rate Limits)
        logger.error(f"Max retries exceeded for {ticker}")
        raise TimeoutError(f"Max retries exceeded for {ticker}")

    def get_financials(self, ticker: str, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Fetch fundamental financial data (Balance Sheet, Income Statement).
        """
        financials = []
        for f in self.client.vx.list_stock_financials(ticker=ticker, limit=limit):
            financials.append(f)
        return financials
            
    def get_tickers(self, market: str = "stocks", active: bool = True) -> List[str]:
        """Fetch all active tickers."""
        tickers = []
        try:
            for t in self.client.list_tickers(market=market, active=active, limit=1000):
                tickers.append(t.ticker)
        except Exception as e:
            logger.error(f"Error fetching tickers: {e}")
        return tickers
