import time
import random
import functools
from utils.logger import logger

def retry_with_backoff(max_retries=5, base_delay=5, max_delay=60, tag="NETWORK"):
    """
    Decorator for exponential backoff retries.
    Args:
        max_retries: Maximum number of retry attempts.
        base_delay: Initial delay in seconds.
        max_delay: Maximum delay in seconds.
        tag: Logger tag for visibility.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            retries = 0
            while retries <= max_retries:
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    retries += 1
                    if retries > max_retries:
                        logger.error(f"Max retries ({max_retries}) reached for {func.__name__}: {e}", tag=tag)
                        raise e
                    
                    err_msg = str(e).lower()
                    # Determine if it's a rate limit (429) or other transient error
                    delay = base_delay * (2 ** (retries - 1)) + random.uniform(0, 1)
                    delay = min(delay, max_delay)
                    
                    if "429" in err_msg or "too many requests" in err_msg:
                        logger.warning(f"Rate limit hit in {func.__name__}. Retrying in {delay:.2f}s... (Attempt {retries}/{max_retries})", tag=tag)
                    else:
                        logger.warning(f"Transient error in {func.__name__}: {e}. Retrying in {delay:.2f}s... (Attempt {retries}/{max_retries})", tag=tag)
                    
                    time.sleep(delay)
            return None
        return wrapper
    return decorator
