import logging
import sys
from config import get_config

config = get_config()

def setup_logger(name="polymarket_bot"):
    """
    Configures and returns a logger instance with a standardized format.
    """
    logger = logging.getLogger(name)
    
    # Set log level from config
    log_level = getattr(logging, config.LOG_LEVEL.upper(), logging.INFO)
    logger.setLevel(log_level)
    
    # Check if the logger already has handlers (to avoid duplicates)
    if not logger.handlers:
        # Create formatter
        formatter = logging.Formatter(
            '%(asctime)s | %(levelname)-8s | %(name)s | %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        # Console Handler
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        # File Handler
        file_handler = logging.FileHandler("bot.log")
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        
    return logger

# Global logger instance
logger = setup_logger()
