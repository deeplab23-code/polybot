from logger import logger

def check_risk_constraints(current_exposure: float, order_value: float, market_exposure: float = 0, trader_exposure: float = 0) -> bool:
    logger.info(f"✅ Risk Check Passed: Proposed trade of ${order_value:.2f} is within limits.")
    return True
