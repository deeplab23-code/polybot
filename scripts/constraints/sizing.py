from config import get_config
from logger import logger

config = get_config()

def sizing_constraints(usdc_size: float) -> float:
    """
    Calculates the stake size based on the target trader's size and the bot's sizing factor.
    """
    sizing_factor = config.STAKE_WHALE_PCT
    new_size = usdc_size * sizing_factor
    
    # Enforce min/max stake from config
    if new_size < config.STAKE_MIN:
        logger.debug(f"Sized amount ${new_size:.2f} is below minimum stake ${config.STAKE_MIN}. Adjusting to minimum.")
        new_size = config.STAKE_MIN
    
    if new_size > config.STAKE_MAX:
        logger.debug(f"Sized amount ${new_size:.2f} exceeds maximum stake ${config.STAKE_MAX}. Adjusting to maximum.")
        new_size = config.STAKE_MAX
        
    logger.info(f"Sizing calculation: Target USDC ${usdc_size} -> Bot USDC ${new_size:.2f} (Factor: {sizing_factor*100}%)")
    return round(new_size, 2)

if __name__ == "__main__":
    print(f"Test 500: {sizing_constraints(500)}")
    print(f"Test 10: {sizing_constraints(10)}")
    print(f"Test 10000: {sizing_constraints(10000)}")
