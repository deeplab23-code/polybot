from config import get_config
from logger import logger

config = get_config()

# Thresholds for risk management
# These could also be moved to config.py if we want them configurable via .env
MAX_SINGLE_MARKET_EXPOSURE_PCT = 0.25  # Max 25% of bankroll in one market
MAX_TRADER_EXPOSURE_PCT = 0.55        # Max 55% of bankroll on one trader's picks

def check_risk_constraints(current_exposure: float, order_value: float, market_exposure: float = 0, trader_exposure: float = 0) -> bool:
    """
    Validates if a proposed trade complies with risk management rules.
    
    Args:
        current_exposure: Total USDC currently in all open positions.
        order_value: The USDC value of the proposed new order.
        market_exposure: Current USDC exposure in this specific market.
        trader_exposure: Current USDC exposure from this specific trader's picks.
        
    Returns:
        bool: True if the trade is allowed, False otherwise.
    """
    bankroll = config.BANKROLL
    
    # 1. Check Total Exposure
    if current_exposure + order_value > bankroll:
        logger.warning(f"🚨 Risk Check Failed: Total exposure ({current_exposure + order_value:.2f}) would exceed bankroll (${bankroll})")
        return False
        
    # 2. Check Single Market Exposure
    max_market = bankroll * MAX_SINGLE_MARKET_EXPOSURE_PCT
    if market_exposure + order_value > max_market:
        logger.warning(f"🚨 Risk Check Failed: Market exposure ({market_exposure + order_value:.2f}) would exceed limit (${max_market:.2f})")
        return False
        
    # 3. Check Single Trader Exposure
    max_trader = bankroll * MAX_TRADER_EXPOSURE_PCT
    if trader_exposure + order_value > max_trader:
        logger.warning(f"🚨 Risk Check Failed: Trader exposure ({trader_exposure + order_value:.2f}) would exceed limit (${max_trader:.2f})")
        return False

    logger.info(f"✅ Risk Check Passed: Proposed trade of ${order_value:.2f} is within limits.")
    return True
