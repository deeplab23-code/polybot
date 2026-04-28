import time
from py_clob_client_v2 import ClobClient, OrderArgs, OrderType, Side, PartialCreateOrderOptions
from config import get_config
from logger import logger
from notifier import send_notification

config = get_config()
_client = None

def _get_client() -> ClobClient:
    global _client
    if _client is None:
        try:
            logger.info(f"Initializing Polymarket CLOB v2 Client (URL: {config.CLOB_API_URL}, Chain ID: {config.POLY_CHAIN_ID})")
            # v2: sin funder ni signature_type para obtener creds
            temp_client = ClobClient(
                host=config.CLOB_API_URL,
                chain_id=config.POLY_CHAIN_ID,
                key=config.PRIVATE_KEY,
            )
            creds = temp_client.create_or_derive_api_key()
            # Cliente autenticado con funder solo en el segundo paso
            _client = ClobClient(
                host=config.CLOB_API_URL,
                chain_id=config.POLY_CHAIN_ID,
                key=config.PRIVATE_KEY,
                creds=creds,
                funder=config.POLY_FUNDER,
                signature_type=2,
            )
            logger.info("CLOB v2 Client initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize CLOB v2 Client: {e}")
            raise
    return _client

def make_order(price: float, size: float, side: str, token_id: str, max_slippage: float = None) -> dict:
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

    minimum_tokens = 5.0
    minimum_notional = 1.0
    required_cost = max(minimum_notional, minimum_tokens * execution_price)

    if required_cost > config.STAKE_MAX:
        logger.info(f"⏭️ Skipping: min order cost ${required_cost:.2f} exceeds STAKE_MAX ${config.STAKE_MAX}")
        return None

    max_affordable_size = config.STAKE_MAX / execution_price
    size = max(size, minimum_tokens)
    size = min(size, max_affordable_size)
    size = round(size, 2)
    estimated_cost = size * execution_price

    logger.info(f"Preparing {side} order: {size} units at price ${execution_price} (Estimated cost: ${estimated_cost:.2f}) for Token ID: {token_id}")

    if config.DRY_RUN:
        logger.info(f"🛡️ DRY RUN: Skipping order for {side} {size} units.")
        return {"success": True, "dry_run": True, "orderID": "DRY_RUN_ID"}

    attempts = 0
    while attempts < config.MAX_RETRY_ATTEMPTS:
        try:
            client = _get_client()
            resp = client.create_and_post_order(
                order_args=OrderArgs(
                    token_id=token_id,
                    price=execution_price,
                    side=clob_side,
                    size=size,
                ),
                options=PartialCreateOrderOptions(tick_size="0.01"),
                order_type=OrderType.GTC,
            )

            if resp:
                order_id = resp.get("orderID") or resp.get("id") or str(resp)
                logger.info(f"✅ Order placed successfully! Order ID: {order_id}")
                send_notification(
                    f"✅ *Order Placed!*\n\nType: {side}\nSize: {size}\nPrice: ${execution_price}\nCost: ${estimated_cost:.2f}\nToken: `{token_id[:16]}...`"
                )
                return {"success": True, "orderID": order_id}
            else:
                logger.warning(f"⚠️ Order placement returned empty response")

        except Exception as e:
            error_str = str(e).lower()
            if "not enough balance" in error_str or "balance is not enough" in error_str:
                logger.info(f"⏭️ Skipping: insufficient balance for ${estimated_cost:.2f} order")
                return None
            logger.error(f"❌ Attempt {attempts + 1} failed with error: {e}")
            global _client
            _client = None

        attempts += 1
        if attempts < config.MAX_RETRY_ATTEMPTS:
            wait_time = config.RETRY_BACKOFF_FACTOR ** attempts
            logger.info(f"🔄 Retrying in {wait_time:.2f} seconds...")
            time.sleep(wait_time)

    logger.critical(f"🛑 Failed to place order after {config.MAX_RETRY_ATTEMPTS} attempts.")
    send_notification(f"🛑 *CRITICAL ERROR: Order Failed!*\n\nFailed to place {side} order for {size} units.")
    return None
