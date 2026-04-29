import asyncio
from datetime import datetime, timezone
import threading
import time
import traceback
from supabase import acreate_client, AsyncClient
from make_orders import make_order
from get_player_positions import fetch_player_positions, insert_player_positions_batch, get_current_exposures
from get_player_history_new import (
    fetch_activities as fetch_history_activities,
    get_new_activities,
)
from constraints.sizing import sizing_constraints
from constraints.risk_manager import check_risk_constraints
from copied_trades import claim_trade, mark_trade, trader_exposure
from py_clob_client_v2 import Side
BUY = Side.BUY
SELL = Side.SELL
from config import get_config
from logger import logger

config = get_config()
url: str = config.SUPABASE_URL
key: str = config.SUPABASE_KEY
TABLE_NAME_POSITIONS = config.TABLE_NAME_POSITIONS
_supabase_client: AsyncClient = None

MAX_HOURS_TO_EXPIRY = 48
MIN_PRICE = 0.10
MIN_REWARD_RISK_RATIO = 1.0

async def get_supabase() -> AsyncClient:
    global _supabase_client
    if _supabase_client is None:
        _supabase_client = await acreate_client(url, key)
    return _supabase_client

def is_target_trader(wallet: str) -> bool:
    if not wallet: return False
    return wallet.lower() in config.TRADER_WALLETS

def is_market_too_far(activity: dict, title: str) -> bool:
    """Devuelve True si el mercado ya venció O cierra en más de MAX_HOURS_TO_EXPIRY horas."""
    end_date = activity.get('end_date')

    if not end_date:
        if "Up or Down" in title:
            return False  # Mercados 15M — siempre corto plazo, permitir
        # Permitir mercados con fecha de hoy en el título
        today = datetime.now(timezone.utc)
        today_strs = [
            today.strftime("%B %-d"),  # "April 29"
            today.strftime("%b %-d"),  # "Apr 29"
        ]
        if any(s in title for s in today_strs):
            return False
        logger.info(f"⏭️  Skipping: no end_date (cannot verify expiry) | {title}")
        return True

    try:
        end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
        hours_left = (end_dt - datetime.now(timezone.utc)).total_seconds() / 3600
        if hours_left < 0:
            logger.info(f"⏭️  Skipping: market already expired | {title}")
            return True
        if hours_left > MAX_HOURS_TO_EXPIRY:
            logger.info(f"⏭️  Skipping: market closes in {hours_left:.0f}h (max {MAX_HOURS_TO_EXPIRY}h) | {title}")
            return True
    except Exception as e:
        logger.warning(f"⏭️  Skipping: end_date parse failed | {title} | {e}")
        return True

    return False

def is_already_in_market(condition_id: str, title: str) -> bool:
    """Devuelve True si ya tenemos una posición abierta en este mercado (persiste en Supabase)."""
    if not condition_id:
        return False
    try:
        from copied_trades import supabase as ct_supabase, TABLE as CT_TABLE
        resp = ct_supabase.table(CT_TABLE)\
            .select("transaction_hash")\
            .eq("condition_id", condition_id)\
            .in_("status", ["claimed", "submitted"])\
            .limit(1)\
            .execute()
        if resp.data:
            logger.info(f"⏭️  Skipping: already have position in market | {title}")
            return True
    except Exception as e:
        logger.warning(f"is_already_in_market check failed: {e}")
    return False

def mark_market_open(condition_id: str) -> None:
    pass  # Ya no necesario — Supabase es la fuente de verdad

def mark_market_closed(condition_id: str) -> None:
    pass  # Ya no necesario — el status en Supabase lo refleja

def process_new_trade(activity: dict):
    try:
        proxy_wallet = (activity.get('proxy_wallet') or '').lower()
        if not is_target_trader(proxy_wallet):
            return
        transaction_hash = activity.get('transaction_hash')
        usdc_size = float(activity.get('usdc_size') or 0)
        side = activity.get('side')
        token_id = activity.get('asset')
        title = activity.get('title', 'N/A')
        price = float(activity.get('price') or 0)
        condition_id = activity.get('condition_id')

        logger.info(f"🎯 New trade from {proxy_wallet[:10]}... | {title} | {side} | ${usdc_size:.2f}")

        if price <= 0:
            logger.info(f"⏭️  Skipping: invalid price {price}")
            return

        # Filtro: precio mínimo 0.10
        if price < MIN_PRICE:
            logger.info(f"⏭️  Skipping: price {price:.3f} too low (min {MIN_PRICE})")
            return

        # Filtro: ratio recompensa/riesgo minimo
        if side == BUY:
            potential_gain = (1 - price) / price
            if potential_gain < MIN_REWARD_RISK_RATIO:
                logger.info(f"Skipping: reward/risk {potential_gain:.2f} < {MIN_REWARD_RISK_RATIO} | {title}")
                return

        # Filtro: mercado vencido o demasiado lejos
        if is_market_too_far(activity, title):
            return

        # Filtro: ya tenemos posición en este mercado
        if side == BUY and is_already_in_market(condition_id, title):
            return

        if side == SELL:
            data_trader = fetch_player_positions(user_address=proxy_wallet, condition_id=condition_id)
            data_myself = fetch_player_positions(user_address=config.POLY_FUNDER, condition_id=condition_id)
            if data_trader and data_myself:
                size_trader = float(data_trader[0].get('size', 0))
                size_myself = float(data_myself[0].get('size', 0))
                if size_trader > 0 and size_myself > 0:
                    pct = usdc_size / size_trader
                    final_size = pct * size_myself
                    if not claim_trade(transaction_hash, proxy_wallet, token_id, side, price, final_size * price, condition_id):
                        return
                    resp = make_order(price=price, size=final_size, side=side, token_id=token_id)
                    mark_trade(transaction_hash, "submitted" if resp and resp.get("success") else "failed", resp.get("orderID") if resp else None)
                    if resp and resp.get("success"):
                        mark_market_closed(condition_id)
        else:
            bot_usdc_size = sizing_constraints(usdc_size)
            if bot_usdc_size <= 0:
                return
            total_exp, market_exps = get_current_exposures(config.POLY_FUNDER)
            t_exp = trader_exposure(proxy_wallet)
            if check_risk_constraints(total_exp, bot_usdc_size, market_exposure=market_exps.get(token_id, 0), trader_exposure=t_exp):
                if not claim_trade(transaction_hash, proxy_wallet, token_id, side, price, bot_usdc_size, condition_id):
                    return
                bot_size_units = bot_usdc_size / price
                logger.info(f"📤 Placing order: {side} {bot_size_units:.4f} units @ ${price} = ${bot_usdc_size:.2f}")
                resp = make_order(price=price, size=bot_size_units, side=side, token_id=token_id)
                mark_trade(transaction_hash, "submitted" if resp and resp.get("success") else "failed", resp.get("orderID") if resp else None)
                if resp and resp.get("success"):
                    logger.info(f"✅ Order placed: {resp.get('orderID')}")
                    mark_market_open(condition_id)
                else:
                    logger.error(f"❌ Order failed: {resp}")
    except Exception as e:
        logger.error(f"❌ Error in process_new_trade: {e}\n{traceback.format_exc()}")

async def handle_new_position(payload):
    try:
        record = payload.get('data', {}).get('record', {})
        proxy_wallet = (record.get('proxy_wallet') or '').lower()
        if not is_target_trader(proxy_wallet): return
        asset = record.get('asset')
        initial_value = float(record.get('initial_value', 0))
        avg_price = float(record.get('avg_price', 0))
        title = record.get('title', 'N/A')
        logger.info(f"📈 New position from {proxy_wallet[:10]}... | {title}")
        bot_usdc_value = sizing_constraints(initial_value)
        if bot_usdc_value > 0 and avg_price > 0:
            total_exp, market_exps = get_current_exposures(config.POLY_FUNDER)
            t_exp = trader_exposure(proxy_wallet)
            if check_risk_constraints(total_exp, bot_usdc_value, market_exposure=market_exps.get(asset, 0), trader_exposure=t_exp):
                make_order(price=avg_price, size=bot_usdc_value / avg_price, side=BUY, token_id=asset)
    except Exception as e:
        logger.error(f"❌ Error in handle_new_position: {e}")

async def handle_update_position(payload):
    try:
        new_record = payload.get('data', {}).get('record', {})
        proxy_wallet = (new_record.get('proxy_wallet') or '').lower()
        if not is_target_trader(proxy_wallet): return
        old_record = payload.get('data', {}).get('old_record', {})
        asset = new_record.get('asset')
        title = new_record.get('title', 'N/A')
        old_value = float(old_record.get('current_value', 0))
        new_value = float(new_record.get('current_value', 0))
        cur_price = float(new_record.get('cur_price', 0))
        delta_value = new_value - old_value
        if abs(delta_value) < 1.0 or cur_price <= 0: return
        logger.info(f"🔄 Position update {proxy_wallet[:10]}... | {title} | Delta: ${delta_value:+.2f}")
        if delta_value > 0:
            sized_delta = sizing_constraints(abs(delta_value))
            if sized_delta <= 0: return
            total_exp, market_exps = get_current_exposures(config.POLY_FUNDER)
            t_exp = trader_exposure(proxy_wallet)
            if check_risk_constraints(total_exp, sized_delta, market_exposure=market_exps.get(asset, 0), trader_exposure=t_exp):
                make_order(price=cur_price, size=sized_delta / cur_price, side=BUY, token_id=asset)
        else:
            old_size_trader = float(old_record.get('size', 1))
            new_size_trader = float(new_record.get('size', 0))
            data_myself = fetch_player_positions(user_address=config.POLY_FUNDER, condition_id=new_record.get('condition_id'))
            if data_myself:
                my_size = float(data_myself[0].get('size', 0))
                reduction_pct = (old_size_trader - new_size_trader) / old_size_trader if old_size_trader > 0 else 0
                make_order(price=cur_price, size=my_size * reduction_pct, side=SELL, token_id=asset)
    except Exception as e:
        logger.error(f"❌ Error in handle_update_position: {e}")

async def listen_to_positions():
    logger.info(f"🔍 Monitoring {TABLE_NAME_POSITIONS} (INSERT)")
    supabase = await get_supabase()
    loop = asyncio.get_event_loop()
    def cb(payload):
        loop.call_soon_threadsafe(asyncio.ensure_future, handle_new_position(payload))
    await supabase.channel("positions-inserts").on_postgres_changes(
        "INSERT", schema="public", table=TABLE_NAME_POSITIONS, callback=cb
    ).subscribe()
    while True: await asyncio.sleep(1)

async def listen_to_updates():
    logger.info(f"🔍 Monitoring {TABLE_NAME_POSITIONS} (UPDATE)")
    supabase = await get_supabase()
    loop = asyncio.get_event_loop()
    def cb(payload):
        loop.call_soon_threadsafe(asyncio.ensure_future, handle_update_position(payload))
    await supabase.channel("positions-updates").on_postgres_changes(
        "UPDATE", schema="public", table=TABLE_NAME_POSITIONS, callback=cb
    ).subscribe()
    while True: await asyncio.sleep(1)

async def run_all_listeners():
    logger.info("🚀 STARTING POLYMARKET MONITORING SYSTEM (Multi-Trader Mode)")
    await asyncio.gather(listen_to_positions(), listen_to_updates())

STOP_LOSS_PCT = 0.50  # Cerrar si pierde más del 50% del valor inicial

def stop_loss_loop():
    """Revisa posiciones propias cada 5 minutos y cierra las que pierden más del STOP_LOSS_PCT."""
    while True:
        try:
            positions = fetch_player_positions(user_address=config.POLY_FUNDER, limit=500, offset=0)
            if not positions:
                time.sleep(60 * 5)
                continue

            for pos in positions:
                try:
                    initial_value = float(pos.get('initialValue') or 0)
                    current_value = float(pos.get('currentValue') or 0)
                    cur_price = float(pos.get('curPrice') or 0)
                    size = float(pos.get('size') or 0)
                    token_id = pos.get('asset')
                    title = pos.get('title', 'N/A')

                    if initial_value <= 0 or cur_price <= 0 or size <= 0:
                        continue

                    # Skip si el precio es demasiado bajo — no hay liquidez
                    if cur_price < 0.05:
                        continue

                    # Skip si el mercado ya expiró o queda menos de 2 minutos
                    end_date = pos.get('endDate')
                    if end_date:
                        try:
                            end_dt = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                            minutes_left = (end_dt - datetime.now(timezone.utc)).total_seconds() / 60
                            if minutes_left < 2:
                                continue
                        except Exception:
                            pass

                    loss_pct = (initial_value - current_value) / initial_value

                    if loss_pct >= STOP_LOSS_PCT:
                        logger.info(f"🛑 Stop loss triggered: {title} | Lost {loss_pct*100:.1f}% | Value: ${current_value:.2f} (was ${initial_value:.2f})")
                        resp = make_order(
                            price=cur_price,
                            size=size,
                            side=SELL,
                            token_id=token_id,
                        )
                        if resp and resp.get('success'):
                            logger.info(f"✅ Stop loss executed: {title} | Recovered ~${current_value:.2f}")
                        else:
                            logger.warning(f"⚠️ Stop loss failed: {title}")

                except Exception as e:
                    logger.error(f"❌ Error in stop loss check for position: {e}")

        except Exception as e:
            logger.error(f"❌ Stop loss loop error: {e}\n{traceback.format_exc()}")

        time.sleep(60)

def _start_polling_threads():
    def poll_history_loop():
        while True:
            for wallet in config.TRADER_WALLETS:
                try:
                    activities = fetch_history_activities(wallet, limit=500, offset=0)
                    if not activities: continue
                    new_activities = get_new_activities(activities, wallet=wallet)
                    if new_activities:
                        logger.info(f"🆕 {len(new_activities)} new from {wallet[:10]}...")
                        for activity in new_activities:
                            process_new_trade(activity)
                except Exception:
                    logger.error(f"Error polling history for {wallet}: {traceback.format_exc()}")
            time.sleep(10)

    def poll_positions_loop():
        while True:
            for wallet in config.TRADER_WALLETS:
                try:
                    positions = fetch_player_positions(user_address=wallet, limit=50, offset=0)
                    if positions: insert_player_positions_batch(positions)
                except Exception:
                    logger.error(f"Error polling positions for {wallet}: {traceback.format_exc()}")
            time.sleep(60 * 5)

    threading.Thread(target=poll_history_loop, daemon=True).start()
    threading.Thread(target=poll_positions_loop, daemon=True).start()
    threading.Thread(target=stop_loss_loop, daemon=True).start()

if __name__ == "__main__":
    config.print_config_summary()
    _start_polling_threads()
    asyncio.run(run_all_listeners())
