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
            temp_client = ClobClient(
                host=config.CLOB_API_URL,
                chain_id=config.POLY_CHAIN_ID,
                key=config.PRIVATE_KEY,
            )
            creds = temp_client.create_or_derive_api_key()
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

    # Precio de ejecución redondeado a 2 decimales
    if side == "BUY" or str(side) == str(Side.BUY):
        if price > 0.95:
            execution_price = min(round(price * 1.001, 2), 0.99)
        else:
            execution_price = min(round(price * (1 + max_slippage), 2), 0.99)
        clob_side = Side.BUY
    else:
        execution_price = max(round(price * (1 - max_slippage), 2), 0.01)
        clob_side = Side.SELL

    minimum_tokens = 1
    max_cost = config.STAKE_MAX

    # Sizing fijo: ignoramos el size del trader, usamos siempre budget fijo
    target_cost = max_cost
    size = int(target_cost / execution_price)

    # Si no podemos pagar el mínimo, skip
    if size < minimum_tokens:
        logger.info(f"⏭️ Skipping: cannot afford minimum {minimum_tokens} tokens at ${execution_price} (max affordable: {size})")
        return None

    # Verificación final — nunca superar max_cost
    estimated_cost = round(size * execution_price, 2)
    while estimated_cost > max_cost and size > 0:
        size -= 1
        estimated_cost = round(size * execution_price, 2)

    if size <= 0 or estimated_cost <= 0:
        logger.info(f"⏭️ Skipping: invalid size {size} or cost ${estimated_cost}")
        return None

    # Validar ratio sobre precio de ejecución real
    if clob_side == Side.BUY:
        real_ratio = (1 - execution_price) / execution_price
        if real_ratio < 1.0:
            logger.info(f"⏭️ Skipping: execution price ${execution_price} ratio {real_ratio:.2f} < 1.0")
            return None

    logger.info(f"Preparing {side} order: {size} tokens @ ${execution_price} = ${estimated_cost:.2f} | Token: {token_id[:16]}...")

    if config.DRY_RUN:
        logger.info(f"🛡️ DRY RUN: Would place {side} {size} tokens @ ${execution_price} = ${estimated_cost:.2f}")
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
                order_type=OrderType.GTC,  # GTC: la orden queda abierta hasta llenarse o cancelarse
            )

            if resp:
                order_id = resp.get("orderID") or resp.get("id") or str(resp)
                logger.info(f"✅ Order placed! ID: {order_id} | {side} {size} tokens @ ${execution_price} = ${estimated_cost:.2f}")
                send_notification(
                    f"✅ *Order Placed*\n\nType: {side}\nTokens: {size}\nPrice: ${execution_price}\nCost: ${estimated_cost:.2f}\nToken: `{token_id[:16]}...`"
                )
                return {"success": True, "orderID": order_id}
            else:
                logger.warning(f"⚠️ Empty response from API")

        except Exception as e:
            error_str = str(e).lower()
            if "not enough balance" in error_str or "balance is not enough" in error_str:
                logger.info(f"⏭️ Skipping: insufficient balance for ${estimated_cost:.2f}")
                return None
            logger.error(f"❌ Attempt {attempts + 1} failed: {e}")
            global _client
            _client = None

        attempts += 1
        if attempts < config.MAX_RETRY_ATTEMPTS:
            wait_time = config.RETRY_BACKOFF_FACTOR ** attempts
            logger.info(f"🔄 Retrying in {wait_time:.2f}s...")
            time.sleep(wait_time)

    logger.critical(f"🛑 Failed after {config.MAX_RETRY_ATTEMPTS} attempts.")
    send_notification(f"🛑 *Order Failed*\n\n{side} {size} tokens @ ${execution_price}")
    return None
