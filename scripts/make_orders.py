import time
from py_clob_client_v2 import (
    ClobClient,
    OrderArgs,
    MarketOrderArgs,
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

    is_buy = side == "BUY" or str(side) == str(Side.BUY)

    original_usd_value = size * price

    usd_to_spend = min(
        max(original_usd_value, config.STAKE_MIN),
        config.STAKE_MAX
    )

    if usd_to_spend < config.STAKE_MIN:
        logger.info(
            f"⏭️ Skipping: ${usd_to_spend:.2f} < STAKE_MIN ${config.STAKE_MIN}"
        )
        return None

    logger.info(
        f"Preparing {side} order | "
        f"Trader value ${original_usd_value:.2f} -> "
        f"Bot spend ${usd_to_spend:.2f}"
    )

    if config.DRY_RUN:
        logger.info(
            f"🛡️ DRY RUN | {side} | "
            f"Spend ${usd_to_spend:.2f} | "
            f"Token {token_id[:12]}..."
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

            # ==========================
            # BUY = exact pUSD amount
            # ==========================
            if is_buy:
                response = client.create_and_post_order(
                    order_args=MarketOrderArgs(
                        token_id=token_id,
                        amount=round(usd_to_spend, 2),
                        side=Side.BUY,
                    )
                )

            # ==========================
            # SELL = shares
            # ==========================
            else:
                adjusted_size = round(size, 2)

                response = client.create_and_post_order(
                    order_args=OrderArgs(
                        token_id=token_id,
                        price=price,
                        side=Side.SELL,
                        size=adjusted_size,
                    ),
                    options=PartialCreateOrderOptions(
                        tick_size="0.01"
                    ),
                    order_type=OrderType.GTC,
                )

            logger.info(f"RAW ORDER RESPONSE: {response}")

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
                    f"✅ *Order Placed*\n\n"
                    f"Type: {side}\n"
                    f"Spend: ${usd_to_spend:.2f}\n"
                    f"Token: `{token_id[:16]}...`"
                )

                return {
                    "success": True,
                    "orderID": order_id,
                }

            logger.warning("⚠️ Empty response from API")

        except Exception as e:
            error_str = str(e).lower()

            if (
                "not enough balance" in error_str
                or "balance is not enough" in error_str
            ):
                logger.info(
                    f"⏭️ Skipping: insufficient balance "
                    f"for ${usd_to_spend:.2f}"
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
                f"🔄 Retrying in {wait_time:.2f}s..."
            )
            time.sleep(wait_time)

    logger.critical(
        f"🛑 Failed after {config.MAX_RETRY_ATTEMPTS} attempts"
    )

    send_notification(
        f"🛑 *Order Failed*\n\n"
        f"{side} ${usd_to_spend:.2f}"
    )

    return None
