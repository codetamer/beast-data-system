import logging
import os
import sys
import threading
import warnings
from datetime import datetime

# Silence globally noisy warnings that clutter the stream
warnings.filterwarnings("ignore", category=FutureWarning)
warnings.filterwarnings("ignore", category=UserWarning)

# God-Level Terminal Aesthetics (ANSI Colors)
logging.addLevelName(25, "AUDIT")

class Colors:
    GOLD = "\033[38;5;220m"
    GREEN = "\033[38;5;82m"
    BLUE = "\033[38;5;75m"
    CYAN = "\033[38;5;87m"
    RED = "\033[38;5;196m"
    GRAY = "\033[38;5;245m"
    RESET = "\033[0m"
    BOLD = "\033[1m"


class PlainFormatter(logging.Formatter):
    """Strips ANSI escape codes for clean log files."""
    def format(self, record):
        import re
        msg = super().format(record)
        return re.sub(r'\x1b\[[0-9;]*[mK]', '', msg)

class SentinelLogger:
    """
    The Sentinel Eye: High-Fidelity Structured Logging for Beast Quant Ingestion.
    """
    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super(SentinelLogger, cls).__new__(cls)
                cls._instance._initialized = False
        return cls._instance

    def setup_ingestion_logging(self, log_path="data/beast_ingestion.log", level=logging.INFO):
        """Standardizes all ingestion output into a single universal log file."""
        with self._lock:
            log_dir = os.path.dirname(log_path)
            if log_dir and not os.path.exists(log_dir):
                os.makedirs(log_dir)

            if sys.stdout.encoding != 'utf-8':
                try: sys.stdout.reconfigure(encoding='utf-8')
                except: pass

            self.logger = logging.getLogger("BeastSentinel")
            self.logger.setLevel(logging.DEBUG)
            self.logger.handlers = []

            c_handler = logging.StreamHandler(sys.stdout)
            c_handler.setLevel(level)
            c_handler.setFormatter(logging.Formatter('%(message)s'))

            f_handler = logging.FileHandler(log_path, mode='a', encoding='utf-8')
            f_handler.setLevel(level)
            f_handler.setFormatter(PlainFormatter('%(asctime)s | %(levelname)-8s | %(message)s'))

            self.logger.addHandler(c_handler)
            self.logger.addHandler(f_handler)
            self._initialized = True
            self.info(f"Universal Ingestion Logger Initialized: {log_path}", tag="SYSTEM")

    def _check_init(self):
        """Ensures the logger is initialized before any logging calls."""
        if not self._initialized:
            self.setup_ingestion_logging()

    def debug(self, msg, tag="SYSTEM"):
        self._check_init()
        self.logger.debug(f"{Colors.GRAY}[{tag}] {msg}{Colors.RESET}")

    def info(self, msg, tag="INFO"):
        self._check_init()
        self.logger.info(f"   {Colors.BLUE}[{tag}]{Colors.RESET} {msg}")

    def success(self, msg, tag="SUCCESS"):
        self._check_init()
        self.logger.info(f"   {Colors.GREEN}✅ [{tag}]{Colors.RESET} {Colors.BOLD}{msg}{Colors.RESET}")

    def warning(self, msg, tag="WARNING"):
        self._check_init()
        self.logger.warning(f" {Colors.GOLD}[!] [{tag}]{Colors.RESET} {msg}")

    def error(self, msg, tag="ERROR"):
        self._check_init()
        self.logger.error(f" {Colors.RED}[X] [{tag}]{Colors.RESET} {Colors.BOLD}{msg}{Colors.RESET}")

    def critical(self, msg, tag="CRITICAL"):
        self._check_init()
        self.logger.critical(f" {Colors.RED}[!!!] [{tag}]{Colors.RESET} {Colors.BOLD}{msg}{Colors.RESET}")

    def exception(self, msg, tag="EXCEPTION"):
        self._check_init()
        import traceback
        tb = traceback.format_exc()
        self.logger.error(f" {Colors.RED}[X] [{tag}]{Colors.RESET} {msg}\n{tb}")

    def audit(self, msg, tag="AUDIT"):
        self._check_init()
        self.logger.info(f"   {Colors.CYAN}║ [{tag}]{Colors.RESET} {Colors.BOLD}{msg}{Colors.RESET}")

    def table(self, data: dict, title="METRICS", headers=("Factor", "Value")):
        self._check_init()
        width = 40
        col1_w = 25
        col2_w = 10
        border = "═" * (width + 4)
        header_row = f"║ {headers[0]:<{col1_w}} │ {headers[1]:>{col2_w}} ║"
        self.logger.info(f"\n{Colors.CYAN}╠{border}╣")
        self.logger.info(f"║ {Colors.BOLD}{title:<{width}}{Colors.RESET}{Colors.CYAN} ║")
        sep_row = f"╟{'─' * (col1_w + 2)}┼{'─' * (col2_w + 2)}╢"
        self.logger.info(sep_row)
        self.logger.info(header_row)
        self.logger.info(sep_row)
        for k, v in data.items():
            val_str = f"{v:.4f}" if isinstance(v, (float, int)) else str(v)
            self.logger.info(f"║ {str(k):<{col1_w}} │ {val_str:>{col2_w}} ║")
        self.logger.info(f"╚{border}╝{Colors.RESET}\n")

# Global Instance
logger = SentinelLogger()
