"""
Idempotency ledger for copied trades.
Each source-trader trade we act on is written here keyed on transaction_hash
BEFORE the order hits Polymarket. A UNIQUE violation on re-insert tells us the
event is a replay (Realtime reconnect, duplicate poll) and we must not place
a second order.
Also used to attribute bot exposure back to the source trader for per-trader
risk caps.
"""
from typing import Optional
from supabase import create_client, Client
from config import get_config
from logger import logger

config = get_config()
supabase: Client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
TABLE = "copied_trades"


def claim_trade(
    transaction_hash: str,
    source_wallet: str,
    asset: str,
    side: str,
    price: float,
    bot_usdc_size: float,
    condition_id: Optional[str] = None,
) -> bool:
    """
    Atomically claim a source-trade for copying. Returns True if this process
    now owns the copy, False if another invocation already claimed it (replay)
    or if we already have an active position in this market (condition_id).
    """
    # Check de condition_id ANTES de insertar — evita duplicados en el mismo mercado
    if condition_id:
        try:
            resp = supabase.table(TABLE)\
                .select("transaction_hash")\
                .eq("condition_id", condition_id)\
                .in_("status", ["claimed", "submitted"])\
                .limit(1)\
                .execute()
            if resp.data:
                logger.info(f"⏭️  Skipping: already have active position in market (condition_id: {condition_id[:12]}...)")
                return False
        except Exception as e:
            logger.warning(f"condition_id check failed: {e}")

    row = {
        "transaction_hash": transaction_hash,
        "source_wallet": source_wallet.lower(),
        "asset": asset,
        "condition_id": condition_id,
        "side": side,
        "price": price,
        "bot_usdc_size": bot_usdc_size,
        "status": "claimed",
    }
    try:
        supabase.table(TABLE).insert(row).execute()
        return True
    except Exception as e:
        msg = str(e).lower()
        if "duplicate" in msg or "unique" in msg or "conflict" in msg or "23505" in msg:
            logger.info(f"↩️  Skipping replay for tx {transaction_hash[:12]}... (already copied)")
            return False
        logger.error(f"❌ claim_trade insert failed for {transaction_hash[:12]}...: {e}")
        return False


def mark_trade(transaction_hash: str, status: str, order_id: Optional[str] = None) -> None:
    """Update the ledger row after the order attempt."""
    update = {"status": status}
    if order_id:
        update["order_id"] = order_id
    try:
        supabase.table(TABLE).update(update).eq(
            "transaction_hash", transaction_hash
        ).execute()
    except Exception as e:
        logger.warning(f"Could not update copied_trades for {transaction_hash[:12]}...: {e}")


def trader_exposure(source_wallet: str) -> float:
    """
    Sum bot_usdc_size of trades copied from this source that are still on the
    book (status in 'claimed' or 'submitted' or 'filled'; not yet closed out).
    """
    try:
        resp = (
            supabase.table(TABLE)
            .select("bot_usdc_size,status")
            .eq("source_wallet", source_wallet.lower())
            .in_("status", ["claimed", "submitted", "filled"])
            .execute()
        )
        return sum(float(r.get("bot_usdc_size") or 0) for r in (resp.data or []))
    except Exception as e:
        logger.warning(f"trader_exposure lookup failed for {source_wallet[:10]}...: {e}")
        return 0.0
