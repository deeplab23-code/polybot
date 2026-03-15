"""
Configuration Management Module for Polymarket Copytrading Bot

This module centralizes all configuration loading and validation,
making it easier to manage environment variables and settings.
"""

import os
import sys
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class ConfigError(Exception):
    """Custom exception for configuration errors"""
    pass


class Config:
    """Central configuration class for the bot"""
    
    def __init__(self):
        """Initialize configuration by loading from environment"""
        self._load_env_vars()
        self._load_sizing_config()
        self._validate_config()
    
    def _load_env_vars(self):
        """Load all environment variables"""
        # Supabase Configuration
        self.SUPABASE_URL = os.getenv("SUPABASE_URL")
        self.SUPABASE_KEY = os.getenv("SUPABASE_KEY")
        
        # Polymarket Configuration
        self.PRIVATE_KEY = os.getenv("PK")
        self.POLY_FUNDER = os.getenv("POLY_FUNDER")
        self.CLOB_API_URL = os.getenv("CLOB_API_URL", "https://clob.polymarket.com")
        self.POLY_CHAIN_ID = int(os.getenv("POLY_CHAIN_ID", "137"))
        
        # Trader Wallet Configuration
        self.TRADER_WALLET_RAW = os.getenv("TRADER_WALLET", "")
        self.TRADER_WALLETS = [w.strip().lower() for w in self.TRADER_WALLET_RAW.split(",") if w.strip()]
        
        # Database Table Names
        self.TABLE_NAME_TRADES = os.getenv("TABLE_NAME_TRADES", "historic_trades")
        self.TABLE_NAME_POSITIONS = os.getenv("TABLE_NAME_POSITIONS", "polymarket_positions")

        # Reliability Configuration
        self.MAX_RETRY_ATTEMPTS = int(os.getenv("MAX_RETRY_ATTEMPTS", "3"))
        self.RETRY_BACKOFF_FACTOR = float(os.getenv("RETRY_BACKOFF_FACTOR", "2.0"))
        self.DEFAULT_SLIPPAGE = float(os.getenv("DEFAULT_SLIPPAGE", "0.01"))  # 1% default slippage
        self.LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
        self.DRY_RUN = os.getenv("DRY_RUN", "True").lower() == "true"

        # Telegram Notifications
        self.TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
        self.TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
    
    def _load_sizing_config(self):
        """Load sizing configuration from environment or use defaults"""
        self.BANKROLL = float(os.getenv("BANKROLL", "1000"))
        self.STAKE_MIN = float(os.getenv("STAKE_MIN", "5"))
        self.STAKE_MAX = float(os.getenv("STAKE_MAX", "20"))
        self.STAKE_WHALE_PCT = float(os.getenv("STAKE_WHALE_PCT", "0.005"))
    
    def _validate_config(self):
        """Validate that all required configuration is present"""
        errors = []
        
        # Check required Supabase credentials
        if not self.SUPABASE_URL:
            errors.append("SUPABASE_URL is not set in .env file")
        if not self.SUPABASE_KEY:
            errors.append("SUPABASE_KEY is not set in .env file")
        
        # Check required Polymarket credentials
        if not self.PRIVATE_KEY:
            errors.append("PK (Private Key) is not set in .env file")
        if not self.POLY_FUNDER:
            errors.append("POLY_FUNDER is not set in .env file")
        
        # Check trader wallet configuration
        if not self.TRADER_WALLETS:
            errors.append("TRADER_WALLET is not set in .env file (provide at least one)")
        
        if errors:
            error_message = "\n❌ Configuration Errors:\n" + "\n".join(f"  - {error}" for error in errors)
            error_message += "\n\n💡 Please check your .env file and ensure all required variables are set."
            error_message += "\n📝 See env.example for a template with all required variables."
            raise ConfigError(error_message)
    
    def get_bankroll(self) -> float:
        """Get the configured bankroll amount"""
        return self.BANKROLL
    
    def get_sizing(self) -> dict:
        """Get the configured sizing parameters"""
        return {
            'stake_min': self.STAKE_MIN,
            'stake_max': self.STAKE_MAX,
            'sizing_whale_pct': self.STAKE_WHALE_PCT
        }
    
    def print_config_summary(self):
        """Print a summary of the loaded configuration"""
        print("=" * 80)
        print("⚙️  CONFIGURATION LOADED")
        print("=" * 80)
        print(f"📊 Supabase URL: {self.SUPABASE_URL}")
        print(f"🔗 CLOB API: {self.CLOB_API_URL}")
        print(f"⛓️  Chain ID: {self.POLY_CHAIN_ID}")
        print(f"📈 Trader Wallets ({len(self.TRADER_WALLETS)}): {', '.join([w[:10]+'...' for w in self.TRADER_WALLETS])}")
        print(f"💰 Bankroll: ${self.get_bankroll()}")
        print(f"📊 Min Stake: ${self.STAKE_MIN}")
        print(f"📊 Max Stake: ${self.STAKE_MAX}")
        print(f"📊 Whale %: {self.STAKE_WHALE_PCT * 100}%")
        print("=" * 80)


# Global configuration instance
_config: Optional[Config] = None


def get_config() -> Config:
    """
    Get the global configuration instance (singleton pattern)
    
    Returns:
        Config: The global configuration instance
    """
    global _config
    if _config is None:
        _config = Config()
    return _config


def reload_config() -> Config:
    """
    Force reload the configuration (useful for testing or config changes)
    
    Returns:
        Config: The newly loaded configuration instance
    """
    global _config
    _config = None
    return get_config()


# Convenience function for backwards compatibility
def load_config() -> Config:
    """Legacy function name for loading config"""
    return get_config()


if __name__ == "__main__":
    # Test configuration loading
    print("🔍 Testing configuration loading...\n")
    try:
        config = get_config()
        config.print_config_summary()
        print("\n✅ Configuration loaded successfully!")
    except ConfigError as e:
        print(f"\n❌ Configuration failed: {e}")
        sys.exit(1)
