import time
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY, SELL
from config import get_config
from logger import logger
from notifier import send_notification

# Load configuration
config = get_config()

# Initialize client singleton
_client = None

def _get_client() -> ClobClient:
    """
    Returns a singleton instance of the ClobClient, initializing it if necessary.
    """
    global _client
    if _client is None:
        try:
            logger.info(f"Initializing Polymarket CLOB Client (URL: {config.CLOB_API_URL}, Chain ID: {config.POLY_CHAIN_ID})")
            _client = ClobClient(
                config.CLOB_API_URL,
                key=config.PRIVATE_KEY,
                chain_id=config.POLY_CHAIN_ID,
                signature_type=1,
                funder=config.POLY_FUNDER,
            )
            # Derive and set API credentials
            _client.set_api_creds(_client.create_or_derive_api_creds())
            logger.info("CLOB Client initialized successfully.")
        except Exception as e:
            logger.error(f"Failed to initialize CLOB Client: {e}")
            raise
    return _client

def make_order(price: float, size: float, side: str, token_id: str, max_slippage: float = None) -> dict:
    """
    Places an order on the Polymarket CLOB with retry logic and optional slippage protection.
    """
    if max_slippage is None:
        max_slippage = config.DEFAULT_SLIPPAGE

    # Apply slippage to price
    if side == BUY:
        execution_price = price * (1 + max_slippage)
    else:
        execution_price = price * (1 - max_slippage)

    # Ensure precision is handled (Polymarket prices are usually 2-4 decimal places, but we use the provided one)
    execution_price = round(execution_price, 4)
    size = round(size, 2)

    logger.info(f"Preparing {side} order: {size} units at price ${execution_price} (Original: ${price}, Slippage: {max_slippage*100}%) for Token ID: {token_id}")

    if config.DRY_RUN:
        logger.info(f"🛡️ DRY RUN: Skipping order placement for {side} {size} units.")
        return {"success": True, "dry_run": True, "orderID": "DRY_RUN_ID"}

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
            
            # Sign and post order
            signed_order = client.create_order(order_args)
            resp = client.post_order(signed_order, OrderType.GTC)
            
            if resp and resp.get("success"):
                order_id = resp.get("orderID")
                logger.info(f"✅ Order placed successfully! Order ID: {order_id}")
                send_notification(f"✅ *Order Placed!*\n\nType: {side}\nSize: {size}\nPrice: ${execution_price}\nToken: `{token_id[:16]}...`")
                return resp
            else:
                logger.warning(f"⚠️ Order placement returned unsuccessful: {resp}")
                # Fallthrough to retry
        except Exception as e:
            logger.error(f"❌ Attempt {attempts + 1} failed with error: {e}")
        
        attempts += 1
        if attempts < config.MAX_RETRY_ATTEMPTS:
            wait_time = config.RETRY_BACKOFF_FACTOR ** attempts
            logger.info(f"🔄 Retrying in {wait_time:.2f} seconds...")
            time.sleep(wait_time)
    
    logger.critical(f"🛑 Failed to place order after {config.MAX_RETRY_ATTEMPTS} attempts.")
    send_notification(f"🛑 *CRITICAL ERROR: Order Failed!*\n\nFailed to place {side} order for {size} units after {config.MAX_RETRY_ATTEMPTS} attempts.")
    return None

if __name__ == "__main__":
    # Test order call
    try:
        make_order(price=0.071, size=14.1, side=BUY, token_id='27745789011483877770092220164639878505910623464021791529418856008078952259643')
    except Exception as e:
        print(f"Test run caught error: {e}")
