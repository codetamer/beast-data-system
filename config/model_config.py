class ModelConfig:
    """
    ===========================================================================
    BEAST QUANT | DATA INGESTION ENGINE CONFIGURATION (v1.0.0)
    ===========================================================================
    Target asset universes and date horizons for the data ingestion pipeline.
    ===========================================================================
    """

    # --- Time Windows & Horizons ---
    TIMEZONE = 'US/Eastern'        # Market timezone for alignment.
    START_DATE = '2020-01-01'      # History anchor for start.
    END_DATE = '2025-12-31'        # Termination point for data fetch.

    
    DAILY_ML_TRAINING_WINDOW = 756  # Days of training lookback buffer.
    STRUCTURAL_WARMUP_DAYS = 252    # Initial data warmup buffer.
    CALENDAR_TO_TRADING_SCALAR = 1.5 # Scaling calendar to trading days.

    # --- Target Universes ---
    STOCKS = [
        'MSFT', 'AMZN', 'GOOGL', 'META', 'AAPL', 'TSLA', 'NVDA', 'TSM', 'PLTR',
        'ASML', 'AVGO', 'JPM', 'V', 'BX', 'LLY', 'KO', 'WMT', 'NFLX', 'CAT',
        'UNH', 'PEP', 'XOM', 'JNJ', 'PG', 'HD', 'MCD', 'COST', 'BAC', 'MS', 
        'GS', 'MRK', 'ABBV', 'GE', 'HON', 'LMT', 'AMD', 'QCOM', 'CRM', 'CVX', 'DIS'
    ]
    
    ETFS = [
        'COPX', 'URA', 'GLD', 'USO', 'KRBN'
    ]
    
    CRYPTO = [
        'X:BTCUSD', 'X:ETHUSD', 'X:LINKUSD', 'X:XRPUSD', 'X:MEMEUSD', 'X:HYPEUSD', 'X:BNBUSD'
    ]

    DAILY_STRATEGY_UNIVERSE = STOCKS + ETFS + CRYPTO
    TICKERS = list(set(DAILY_STRATEGY_UNIVERSE))

    # --- Macro Tickers ---
    VIX_SYMBOL = '^VIX'
    DXY_SYMBOL = 'DX-Y.NYB'