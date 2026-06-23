import re

def to_yfinance_ticker(polygon_ticker: str) -> str:
    """
    Maps Polygon symbol formats to YFinance formats.
    
    Examples:
    - X:BTCUSD  -> BTC-USD (Crypto)
    - I:SPX     -> ^GSPC (Index - approximation if needed, though usually use ETFs)
    - AAPL      -> AAPL (Stocks - identical)
    - BTCUSD    -> BTC-USD
    """
    # 1. Handle Crypto (X:BTCUSD or BTCUSD)
    if polygon_ticker.startswith('X:'):
        ticker = polygon_ticker.replace('X:', '')
        # Usually BTCUSD -> BTC-USD
        if ticker.endswith('USD'):
            return f"{ticker[:-3]}-USD"
        return ticker # Fallback
    
    # 2. Handle common non-prefixed Crypto if passed
    crypto_patterns = ['BTCUSD', 'ETHUSD', 'SOLUSD']
    if polygon_ticker in crypto_patterns:
         return f"{polygon_ticker[:-3]}-USD"

    # 3. Handle Indices (Polygon uses I: prefix)
    if polygon_ticker == 'I:SPX' or polygon_ticker == 'SPX':
        return "^GSPC" # S&P 500
    if polygon_ticker == 'I:NDX' or polygon_ticker == 'NDX':
        return "^NDX" # Nasdaq 100
    if polygon_ticker == 'I:VIX' or polygon_ticker == 'VIX':
        return "^VIX" # VIX Index
        
    # 4. Standard Stocks
    return polygon_ticker

def to_polygon_ticker(yfinance_ticker: str) -> str:
    """Reverse mapping if needed."""
    if '-' in yfinance_ticker:
        # BTC-USD -> X:BTCUSD
        return f"X:{yfinance_ticker.replace('-', '')}"
    if yfinance_ticker.startswith('^'):
        # ^GSPC -> I:SPX (approx)
        if yfinance_ticker == "^GSPC": return "I:SPX"
        if yfinance_ticker == "^VIX": return "I:VIX"
    return yfinance_ticker
