import time
from py_clob_client_v2 import (
    ClobClient,
    OrderArgs,
    OrderType,
    Side,
    PartialCreateOrderOptions,
)

from config import get_config
from logger import logger
from notifier import send_notification

config = get_config()
_client = None


def _get_client() -> ClobClient:
    global _client

    if _client is None:
        try:
            logger.info(
                f"Initializing Polymarket CLOB v2 Client "
                f"(URL: {config.CLOB_API_URL}, Chain ID: {config.POLY_CHAIN_ID})"
            )

            temp_client = ClobClient(
                host=config.CLOB_API_URL,
                chain_id=config.POLY_CHAIN_ID,
                key=config.PRIVATE_KEY,
                funder=config.POLY_FUNDER,
                signature_type=2,
            )

            creds = temp_client.create_or_derive_api_key()

            _client = ClobClient(
                host=config.CLOB_API_URL,
                chain_id=config.POLY_CHAIN_ID,
                key=config.PRIVATE_KEY,
                funder=config.POLY_FUNDER,
                signature_type=2,
                creds=creds,
            )

            logger.info("CLOB v2 Client initialized successfully.")

        except Exception as e:
            logger.error(f"Failed to initialize CLOB client: {e}")
            raise

    return _client


def make_order(
    price: float,
    size: float,
    side: str,
    token_id: str,
    max_slippage: float = None,
) -> dict:

    if max_slippage is None:
        max_slippage = config.DEFAULT_SLIPPAGE

    if side == "BUY" or str(side) == str(Side.BUY):
        if price > 0.95:
            execution_price = min(round(price * 1.001, 4), 0.999)
        else:
            execution_price = min(round(price * (1 + max_slippage), 4), 0.999)

        clob_side = Side.BUY

    else:
        execution_price = max(round(price * (1 - max_slippage), 4), 0.001)
        clob_side = Side.SELL

    # ---------------------------------------------------------
    # IMPORTANT V2 FIX:
    # incoming size = copied trader shares
    # convert to original USD value first
    # then clamp between STAKE_MIN and STAKE_MAX
    # then convert back into shares at execution price
    # ---------------------------------------------------------

    original_usd_value = size * price

    usd_to_spend = min(
        max(original_usd_value, config.STAKE_MIN),
        config.STAKE_MAX
    )

    adjusted_size = round(usd_to_spend / execution_price, 2)
    estimated_cost = round(adjusted_size * execution_price, 2)

    if estimated_cost < config.STAKE_MIN:
        logger.info(
            f"⏭️ Skipping: estimated cost ${estimated_cost:.2f} "
            f"is below STAKE_MIN ${config.STAKE_MIN}"
        )
        return None

    logger.info(
        f"Preparing {side} order | "
        f"Original trader value: ${original_usd_value:.2f} | "
        f"Bot spend: ${estimated_cost:.2f} | "
        f"Shares: {adjusted_size} | "
        f"Price: ${execution_price} | "
        f"Token: {token_id}"
    )

    if config.DRY_RUN:
        logger.info(
            f"🛡️ DRY RUN: {side} {adjusted_size} shares "
            f"for ${estimated_cost:.2f}"
        )

        return {
            "success": True,
            "dry_run": True,
            "orderID": "DRY_RUN_ID",
        }

    attempts = 0

    while attempts < config.MAX_RETRY_ATTEMPTS:
        try:
            client = _get_client()

            response = client.create_and_post_order(
                order_args=OrderArgs(
                    token_id=token_id,
                    price=execution_price,
                    side=clob_side,
                    size=adjusted_size,
                ),
                options=PartialCreateOrderOptions(
                    tick_size="0.01"
                ),
                order_type=OrderType.GTC,
            )

            if response:
                order_id = (
                    response.get("orderID")
                    or response.get("id")
                    or str(response)
                )

                logger.info(
                    f"✅ Order placed successfully! "
                    f"Order ID: {order_id}"
                )

                send_notification(
                    f"✅ *Order Placed!*\n\n"
                    f"Type: {side}\n"
                    f"Spend: ${estimated_cost:.2f}\n"
                    f"Shares: {adjusted_size}\n"
                    f"Price: ${execution_price}\n"
                    f"Token: `{token_id[:16]}...`"
                )

                return {
                    "success": True,
                    "orderID": order_id,
                }

            logger.warning("⚠️ Empty response from order API")

        except Exception as e:
            error_str = str(e).lower()

            if (
                "not enough balance" in error_str
                or "balance is not enough" in error_str
            ):
                logger.info(
                    f"⏭️ Skipping: insufficient balance "
                    f"for ${estimated_cost:.2f} order"
                )
                return None

            logger.error(
                f"❌ Attempt {attempts + 1} failed: {e}"
            )

            global _client
            _client = None

        attempts += 1

        if attempts < config.MAX_RETRY_ATTEMPTS:
            wait_time = config.RETRY_BACKOFF_FACTOR ** attempts

            logger.info(
                f"🔄 Retrying in {wait_time:.2f} seconds..."
            )

            time.sleep(wait_time)

    logger.critical(
        f"🛑 Failed after {config.MAX_RETRY_ATTEMPTS} attempts."
    )

    send_notification(
        f"🛑 *CRITICAL ERROR*\n\n"
        f"Failed to place {side} order.\n"
        f"Spend attempted: ${estimated_cost:.2f}"
    )

    return None
