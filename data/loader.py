import pandas as pd
from sqlalchemy import create_engine, text
from config.settings import DB_URI

engine = create_engine(DB_URI)

def load_market_data(start_date: str, end_date: str, symbols: list = None) -> pd.DataFrame:
    """
    Fetches daily market data.
    """
    query = """
    SELECT time, symbol, open, high, low, close, volume 
    FROM market_data_daily 
    WHERE time >= :start AND time <= :end
    """
    params = {"start": start_date, "end": end_date}
    if symbols:
        symbols_str = ", ".join(f"'{s}'" for s in symbols)
        query += f" AND symbol IN ({symbols_str})"
        
    df = pd.read_sql(text(query), engine, params=params)
    if df.empty:
        return pd.DataFrame()
        
    df['time'] = pd.to_datetime(df['time'])
    df = df.set_index(['time', 'symbol']).sort_index()
    return df

def load_fundamentals(start_date: str, end_date: str, symbols: list = None) -> pd.DataFrame:
    """
    Fetches point-in-time fundamental data using publication dates.
    """
    query = """
    SELECT pub_date, symbol, metric, value 
    FROM fundamentals 
    WHERE pub_date >= :start AND pub_date <= :end
    """
    params = {"start": start_date, "end": end_date}
    if symbols:
        symbols_str = ", ".join(f"'{s}'" for s in symbols)
        query += f" AND symbol IN ({symbols_str})"
        
    df = pd.read_sql(text(query), engine, params=params)
    df['pub_date'] = pd.to_datetime(df['pub_date']).dt.tz_localize(None).dt.normalize()
    return df

def load_pivoted_fundamentals(start_date: str, end_date: str, symbols: list = None, metrics: list = None) -> dict:
    """
    Fetches and pivots fundamental data by metric.
    Returns: dict of {metric_name: DataFrame(index=date, columns=symbol)}
    """
    query = """
    SELECT pub_date, symbol, metric, value 
    FROM fundamentals 
    WHERE pub_date <= :end
    """
    params = {"end": end_date}
    if symbols:
        symbols_str = ", ".join(f"'{s}'" for s in symbols)
        query += f" AND symbol IN ({symbols_str})"
    if metrics:
        metrics_str = ", ".join(f"'{m}'" for m in metrics)
        query += f" AND metric IN ({metrics_str})"
        
    df = pd.read_sql(text(query), engine, params=params)
    if df.empty:
        return {}
        
    df['pub_date'] = pd.to_datetime(df['pub_date']).dt.tz_localize(None).dt.normalize()
    df = df.sort_values('pub_date').drop_duplicates(subset=['pub_date', 'symbol', 'metric'], keep='last')
    
    pivoted = {}
    for metric in df['metric'].unique():
        m_df = df[df['metric'] == metric]
        piv = m_df.pivot(index='pub_date', columns='symbol', values='value')
        pivoted[metric] = piv
        
    return pivoted

def load_macro_data(start_date: str, end_date: str, metric: str = 'VIX') -> pd.Series:
    """
    Fetches macro indicators from the dedicated macro_data table.
    """
    query = """
    SELECT time, value 
    FROM macro_data 
    WHERE metric = :metric AND time >= :start AND time <= :end
    """
    params = {"metric": metric, "start": start_date, "end": end_date}
    
    df = pd.read_sql(text(query), engine, params=params)
    
    # Fallback to market_data if VIX was ingested as a ticker
    if df.empty and metric == 'VIX':
        vix_sym = getattr(ModelConfig, 'VIX_SYMBOL', '^VIX')
        query_alt = """
        SELECT time, close as value 
        FROM market_data_daily 
        WHERE (symbol = 'VIX' OR symbol = '^VIX' OR symbol = :vix_sym) AND time >= :start AND time <= :end
        """
        df = pd.read_sql(text(query_alt), engine, params={"start": start_date, "end": end_date, "vix_sym": vix_sym})
        
    if df.empty:
        return pd.Series(dtype=float)
        
    df['time'] = pd.to_datetime(df['time'])
    return df.set_index('time')['value']
