import asyncio
from datetime import datetime
import threading
import time
import traceback
from supabase import acreate_client, AsyncClient
from make_orders import make_order
from get_player_positions import fetch_player_positions, insert_player_positions_batch, get_current_exposures
from get_player_history_new import (
    fetch_activities as fetch_history_activities,
    insert_activities_batch as insert_history_batch,
)
from constraints.sizing import sizing_constraints
from constraints.risk_manager import check_risk_constraints
from py_clob_client.order_builder.constants import BUY, SELL
from config import get_config
from logger import logger

# Load configuration
config = get_config()

# Config Supabase
url: str = config.SUPABASE_URL
key: str = config.SUPABASE_KEY
TABLE_NAME_TRADES = config.TABLE_NAME_TRADES
TABLE_NAME_POSITIONS = config.TABLE_NAME_POSITIONS

# Shared Supabase Client
_supabase_client: AsyncClient = None

async def get_supabase() -> AsyncClient:
    global _supabase_client
    if _supabase_client is None:
        _supabase_client = await acreate_client(url, key)
    return _supabase_client

def is_target_trader(wallet: str) -> bool:
    """Checks if a wallet is in our target list."""
    if not wallet: return False
    return wallet.lower() in config.TRADER_WALLETS

async def handle_new_trade(payload):
    try:
        record = payload.get('data', {}).get('record', {})
        proxy_wallet = record.get('proxy_wallet', '').lower()
        
        # ONLY copy trades from target wallets
        if not is_target_trader(proxy_wallet):
            logger.debug(f"Ignoring trade from non-target wallet: {proxy_wallet}")
            return None

        transaction_hash = record.get('transaction_hash')
        usdc_size = float(record.get('usdc_size', 0))
        side = record.get('side')
        token_id = record.get('asset')
        title = record.get('title')
        price = float(record.get('price', 0))
        condition_id = record.get('condition_id')
        
        logger.info(f"🎯 Copying trade from target: {proxy_wallet[:10]}... | {title} | {side}")

        if side == SELL:
            logger.info(f"⏭️  Side is SELL, calculating proportional size...")
            data_trader = fetch_player_positions(user_address=proxy_wallet, condition_id=condition_id)
            data_myself = fetch_player_positions(user_address=config.POLY_FUNDER, condition_id=condition_id)
            
            if data_trader and data_myself:
                size_trader = float(data_trader[0].get('size', 0))
                size_myself = float(data_myself[0].get('size', 0))
                
                if size_trader > 0:
                    percentage_position = usdc_size / size_trader
                    final_size = percentage_position * size_myself
                    logger.info(f"Selling {percentage_position*100:.2f}% of position: {final_size:.2f} units")
                    return make_order(price=price, size=final_size, side=side, token_id=token_id)
            return None
        else:
            bot_usdc_size = sizing_constraints(usdc_size)
            if bot_usdc_size >= 1:
                total_exp, market_exps = get_current_exposures(config.POLY_FUNDER)
                if check_risk_constraints(total_exp, bot_usdc_size, market_exposure=market_exps.get(token_id, 0)):
                    bot_size_units = bot_usdc_size / price
                    return make_order(price=price, size=bot_size_units, side=side, token_id=token_id)
            return None
    except Exception as e:
        logger.error(f"❌ Error in handle_new_trade: {e}")
        return None

async def handle_new_position(payload):
    try:
        record = payload.get('data', {}).get('record', {})
        proxy_wallet = record.get('proxyWallet', '').lower()
        
        if not is_target_trader(proxy_wallet):
            return None

        asset = record.get('asset')
        initial_value = float(record.get('initialValue', 0))
        avg_price = float(record.get('avgPrice', 0))
        title = record.get('title', 'N/A')

        logger.info(f"📈 New position from target: {proxy_wallet[:10]}... | {title}")

        bot_usdc_value = sizing_constraints(initial_value)
        if bot_usdc_value >= 1:
            total_exp, market_exps = get_current_exposures(config.POLY_FUNDER)
            if check_risk_constraints(total_exp, bot_usdc_value, market_exposure=market_exps.get(asset, 0)):
                bot_size_units = bot_usdc_value / avg_price
                return make_order(price=avg_price, size=bot_size_units, side=BUY, token_id=asset)
        return None
    except Exception as e:
        logger.error(f"❌ Error in handle_new_position: {e}")
        return None

async def handle_update_position(payload):
    try:
        new_record = payload.get('data', {}).get('record', {})
        proxy_wallet = new_record.get('proxyWallet', '').lower()
        
        if not is_target_trader(proxy_wallet):
            return None

        old_record = payload.get('data', {}).get('old_record', {})
        asset = new_record.get('asset')
        title = new_record.get('title', 'N/A')
        old_value = float(old_record.get('current_value', 0))
        new_value = float(new_record.get('current_value', 0))
        cur_price = float(new_record.get('cur_price', 0))
        
        delta_value = new_value - old_value
        if abs(delta_value) < 1.0: return None

        logger.info(f"🔄 Update from target: {proxy_wallet[:10]}... | {title} | Delta: ${delta_value:+.2f}")
        sized_delta = sizing_constraints(abs(delta_value))
        
        if delta_value > 0:
            total_exp, market_exps = get_current_exposures(config.POLY_FUNDER)
            if check_risk_constraints(total_exp, sized_delta, market_exposure=market_exps.get(asset, 0)):
                bot_size_units = sized_delta / cur_price
                return make_order(price=cur_price, size=bot_size_units, side=BUY, token_id=asset)
        else:
            old_size_trader = float(old_record.get('size', 1))
            new_size_trader = float(new_record.get('size', 0))
            data_myself = fetch_player_positions(user_address=config.POLY_FUNDER, condition_id=new_record.get('condition_id'))
            if data_myself:
                my_current_size = float(data_myself[0].get('size', 0))
                reduction_pct = (old_size_trader - new_size_trader) / old_size_trader
                my_reduction_size = my_current_size * reduction_pct
                return make_order(price=cur_price, size=my_reduction_size, side=SELL, token_id=asset)
        return None
    except Exception as e:
        logger.error(f"❌ Error in handle_update_position: {e}")
        return None

async def listen_to_positions():
    logger.info(f"🔍 Monitoring {TABLE_NAME_POSITIONS} (INSERT)")
    supabase = await get_supabase()
    await supabase.channel("positions-inserts").on_postgres_changes(
        "INSERT", schema="public", table=TABLE_NAME_POSITIONS, callback=handle_new_position
    ).subscribe()
    while True: await asyncio.sleep(1)

async def listen_to_updates():
    logger.info(f"🔍 Monitoring {TABLE_NAME_POSITIONS} (UPDATE)")
    supabase = await get_supabase()
    await supabase.channel("positions-updates").on_postgres_changes(
        "UPDATE", schema="public", table=TABLE_NAME_POSITIONS, callback=handle_update_position
    ).subscribe()
    while True: await asyncio.sleep(1)

async def listen_to_trades():
    logger.info(f"🔍 Monitoring {TABLE_NAME_TRADES} (INSERT)")
    supabase = await get_supabase()
    await supabase.channel("trades-inserts").on_postgres_changes(
        "INSERT", schema="public", table=TABLE_NAME_TRADES, callback=handle_new_trade
    ).subscribe()
    while True: await asyncio.sleep(1)

async def run_all_listeners():
    logger.info("🚀 STARTING POLYMARKET MONITORING SYSTEM (Multi-Trader Mode)")
    await asyncio.gather(listen_to_trades(), listen_to_positions(), listen_to_updates())

def _start_polling_threads():
    def poll_history_loop():
        while True:
            for wallet in config.TRADER_WALLETS:
                try:
                    activities = fetch_history_activities(wallet, limit=500, offset=0)
                    if activities: insert_history_batch(activities)
                except Exception: logger.error(f"Error polling history for {wallet}: {traceback.format_exc()}")
            time.sleep(10)

    def poll_positions_loop():
        while True:
            for wallet in config.TRADER_WALLETS:
                try:
                    positions = fetch_player_positions(user_address=wallet, limit=50, offset=0)
                    if positions: insert_player_positions_batch(positions)
                except Exception: logger.error(f"Error polling positions for {wallet}: {traceback.format_exc()}")
            time.sleep(60 * 5)

    threading.Thread(target=poll_history_loop, daemon=True).start()
    threading.Thread(target=poll_positions_loop, daemon=True).start()

if __name__ == "__main__":
    config.print_config_summary()
    _start_polling_threads()
    asyncio.run(run_all_listeners())
