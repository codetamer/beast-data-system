from datetime import datetime
import pytz
import pandas as pd
from config.model_config import ModelConfig

class MarketClock:
    """
    Unified Time Authority for the Beast Ecosystem.
    Enforces New York (US/Eastern) time for all logic decisions.
    
    Usage:
        - Replace datetime.now() with MarketClock.now()
        - Replace datetime.today() with MarketClock.today()
    """
    
    MARKET_TZ = pytz.timezone(ModelConfig.TIMEZONE)
    
    @classmethod
    def now(cls) -> datetime:
        """Returns the current time in US/Eastern timezone."""
        return datetime.now(cls.MARKET_TZ)
    
    @classmethod
    def today(cls) -> datetime:
        """Returns the current date (midnight) in US/Eastern timezone with the correct DST offset."""
        now = cls.now()
        local_midnight = datetime.combine(now.date(), datetime.min.time())
        return cls.MARKET_TZ.localize(local_midnight)
    
    @classmethod
    def get_lookback_date(cls, days: int) -> datetime:
        """Returns (Today - Days) in US/Eastern timezone, robust against DST shifts."""
        naive_today = cls.today().replace(tzinfo=None)
        naive_lookback = naive_today - pd.Timedelta(days=days)
        return cls.MARKET_TZ.localize(naive_lookback)
    
    @classmethod
    def current_date_str(cls) -> str:
        """Returns YYYY-MM-DD string in US/Eastern."""
        return cls.now().strftime('%Y-%m-%d')
