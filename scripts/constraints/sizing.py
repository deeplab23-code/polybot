from config import get_config
from logger import logger

config = get_config()

def sizing_constraints(usdc_size: float) -> float:
    sizing_factor = config.STAKE_WHALE_PCT
    new_size = usdc_size * sizing_factor

    if new_size < config.STAKE_MIN:
        logger.info(f"⏭️  Skipping: ${new_size:.2f} < STAKE_MIN ${config.STAKE_MIN}")
        return 0.0

    if new_size > config.STAKE_MAX:
        new_size = config.STAKE_MAX

    logger.info(f"✅ Sizing: Trader ${usdc_size:.2f} → Bot ${new_size:.2f}")
    return round(new_size, 2)
