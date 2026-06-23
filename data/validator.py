import sys
import os
import pandas as pd
import numpy as np

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from utils.logger import logger


class DataValidator:
    """
    Sovereign Validation Layer for Ingestion Integrity.
    """
    
    @staticmethod
    def validate_adjustment_bridge(ticker, poly_bars, yf_bars):
        """
        Compares adjustment ratios between Polygon and YFinance.
        If they diverge, we have a data corruption risk.
        """
        if not poly_bars or not yf_bars:
            return True # Nothing to compare
            
        p_df = pd.DataFrame(poly_bars)
        y_df = pd.DataFrame(yf_bars)
        
        # Build ratios
        p_df['p_ratio'] = p_df['adj_close'] / p_df['close']
        y_df['y_ratio'] = y_df['adj_close'] / y_df['close']
        
        # Align on timestamps
        merged = pd.merge(
            p_df[['timestamp', 'p_ratio']], 
            y_df[['timestamp', 'y_ratio']], 
            on='timestamp', 
            how='inner'
        )
        
        if merged.empty:
            return True # No overlapping dates to validate
            
        # Check divergence
        merged['diff'] = (merged['p_ratio'] - merged['y_ratio']).abs()
        max_diff = merged['diff'].max()
        
        if max_diff > 0.001: # 0.1% tolerance
            logger.warning(f"ADJUSTMENT DIVERGENCE: {ticker} has {max_diff:.4f} ratio mismatch between sources!", tag="VALIDATOR")
            return False
            
        return True

    @staticmethod
    def detect_vertical_jumps(df, ticker, threshold=0.3):
        """
        Detects absolute price jumps that aren't explained by adjustments.
        Prevents "Ghost Momentum" from bad data.
        """
        if df.empty or len(df) < 2:
            return True
            
        df = df.sort_values('time')
        df['ret'] = df['adj_close'].pct_change().abs()
        
        violent_jumps = df[df['ret'] > threshold]
        if not violent_jumps.empty:
            for idx, row in violent_jumps.iterrows():
                logger.warning(f"SUSPICIOUS JUMP: {ticker} moved {row['ret']:.1%} on {row['time'].date()}", tag="VALIDATOR")
            return False
            
        return True
