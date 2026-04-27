import time
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY, SELL
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
                f"Initializing Polymarket CLOB Client "
                f"(URL: {config.CLOB_API_URL}, Chain ID: {config.POLY_CHAIN_ID})"
            )
            _client = ClobClient(
                config.CLOB_API_URL,
                key=config.PRIVATE_KEY,
                chain_id=config.POLY_CHAIN_ID,
                signature_type=2,
                funder=config.POLY_FUNDER,
            )
            _client.set_api_creds(_client.create_or_derive_api_creds())
            logger.info("CLOB Client initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize CLOB Client: {e}")
            raise
    return _client


def make_order(price: float, size: float, side: str, token_id: str, max_slippage: float = None) -> dict:
    """
    Places an order on Polymarket CLOB.

    Rules:
    - Never exceed STAKE_MAX
    - Respect Polymarket minimum:
        * minimum 5 tokens
        * minimum ~$1 notional
    """

    if max_slippage is None:
        max_slippage = config.DEFAULT_SLIPPAGE

    # Apply slippage
    if side == BUY:
        if price > 0.95:
            execution_price = min(round(price * 1.001, 4), 0.999)
        else:
            execution_price = min(round(price * (1 + max_slippage), 4), 0.999)
    else:
        execution_price = max(round(price * (1 - max_slippage), 4), 0.001)

    minimum_tokens = 5.0
    minimum_notional = 1.0

    required_cost = max(minimum_notional, minimum_tokens * execution_price)

    if required_cost > config.STAKE_MAX:
        logger.info(
            f"⏭️ Skipping trade: minimum valid order costs "
            f"${required_cost:.2f}, above STAKE_MAX ${config.STAKE_MAX}"
        )
        return None

    max_affordable_size = config.STAKE_MAX / execution_price

    size = max(size, minimum_tokens)
    size = min(size, max_affordable_size)
    size = round(size, 2)

    estimated_cost = size * execution_price

    logger.info(
        f"Preparing {side} order: {size} units at price ${execution_price} "
        f"(Estimated cost: ${estimated_cost:.2f}) "
        f"(Original price: ${price}, Slippage: {max_slippage*100}%) "
        f"for Token ID: {token_id}"
    )

    if config.DRY_RUN:
        logger.info(f"🛡️ DRY RUN: Skipping order placement for {side} {size} units.")
        return {
            "success": True,
            "dry_run": True,
            "orderID": "DRY_RUN_ID"
        }

    attempts = 0

    while attempts < config.MAX_RETRY_ATTEMPTS:
        try:
            client = _get_client()

            order_args = OrderArgs(
                price=execution_price,
                size=size,
                side=side,
                token_id=token_id,
            )

            signed_order = client.create_order(order_args)
            resp = client.post_order(signed_order, OrderType.GTC)

            if resp and resp.get("success"):
                order_id = resp.get("orderID")

                logger.info(f"✅ Order placed successfully! Order ID: {order_id}")

                send_notification(
                    f"✅ *Order Placed!*\n\n"
                    f"Type: {side}\n"
                    f"Size: {size}\n"
                    f"Price: ${execution_price}\n"
                    f"Cost: ${estimated_cost:.2f}\n"
                    f"Token: `{token_id[:16]}...`"
                )

                return resp

            else:
                logger.warning(f"⚠️ Order placement returned unsuccessful: {resp}")

        except Exception as e:
            logger.error(f"❌ Attempt {attempts + 1} failed with error: {e}")

        attempts += 1

        if attempts < config.MAX_RETRY_ATTEMPTS:
            wait_time = config.RETRY_BACKOFF_FACTOR ** attempts
            logger.info(f"🔄 Retrying in {wait_time:.2f} seconds...")
            time.sleep(wait_time)

    logger.critical(f"🛑 Failed to place order after {config.MAX_RETRY_ATTEMPTS} attempts.")

    send_notification(
        f"🛑 *CRITICAL ERROR: Order Failed!*\n\n"
        f"Failed to place {side} order for {size} units "
        f"after {config.MAX_RETRY_ATTEMPTS} attempts."
    )

    return None
