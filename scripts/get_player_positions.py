# Code to get player positions and detect if any position exceeds the defined limit
import requests
from supabase import create_client, Client
from config import get_config
from logger import logger

# Load configuration
config = get_config()

# config supabase
supabase: Client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)

API_URL = 'https://data-api.polymarket.com/positions'
TABLE_NAME = config.TABLE_NAME_POSITIONS

def fetch_player_positions(user_address: str, limit: int = 500, offset: int = 0, condition_id: str = None):
    try:
        params = {
            "user": user_address,
            "limit": str(limit),
            "offset": str(offset),
            "sortBy": "INITIAL",
            "sortDirection": "DESC",
        }
        # Only include conditionId when there is a value
        if condition_id is not None:
            params["conditionId"] = condition_id
        
        response = requests.get(API_URL, params=params, timeout=5)
        response.raise_for_status()
        data = response.json()
        logger.debug(f"Fetched {len(data)} positions for {user_address}")
        return data
    
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Request error fetching positions for {user_address}: {e}")
        return None

def get_current_exposures(user_address: str):
    """
    Calculates current exposures for a given wallet.
    Returns: (total_exposure, market_exposures_dict)
    """
    positions = fetch_player_positions(user_address)
    if not positions:
        return 0, {}
    
    total_exposure = 0
    market_exposures = {}
    
    for pos in positions:
        val = float(pos.get('currentValue', 0))
        asset = pos.get('asset')
        total_exposure += val
        market_exposures[asset] = market_exposures.get(asset, 0) + val
        
    return total_exposure, market_exposures

def transform_position_to_db_format(position: dict) -> dict:
    """
    Transforms API format to database format
    """
    # Handle end_date: convert empty string or None to NULL
    end_date = position.get('endDate')
    if not end_date or end_date == '':
        end_date = None
    
    # Handle eventId: convert string to int, or None if empty
    event_id = position.get('eventId')
    if event_id:
        try:
            event_id = int(event_id)
        except (ValueError, TypeError):
            event_id = None
    else:
        event_id = None
    
    return {
       'proxy_wallet': position.get('proxyWallet'),
       'asset': position.get('asset'),
       'condition_id': position.get('conditionId'),
       'size': position.get('size'),
       'avg_price': position.get('avgPrice'),
       'initial_value': position.get('initialValue'),
       'current_value': position.get('currentValue'),
       'cash_pnl': position.get('cashPnl'),
       'percent_pnl': position.get('percentPnl'),
       'total_bought': position.get('totalBought'),
       'realized_pnl': position.get('realizedPnl'),
       'percent_realized_pnl': position.get('percentRealizedPnl'),
       'cur_price': position.get('curPrice'),
       'redeemable': position.get('redeemable'),
       'mergeable': position.get('mergeable'),
       'title': position.get('title'),
       'slug': position.get('slug'),
       'icon': position.get('icon'),
       'event_id': event_id,
       'event_slug': position.get('eventSlug'),
       'outcome': position.get('outcome'),
       'outcome_index': position.get('outcomeIndex'),
       'opposite_outcome': position.get('oppositeOutcome'),
       'opposite_asset': position.get('oppositeAsset'),
       'end_date': end_date,
       'negative_risk': position.get('negativeRisk'),
    }

def insert_player_positions_batch(positions: list):
    """
    Inserts or updates positions only if there are significant changes.
    """
    if not positions:
        logger.info("No positions to insert")
        return 0

    success_count = 0
    error_count = 0
    skipped_count = 0
    
    for idx, position in enumerate(positions, 1):
        try:
            db_position = transform_position_to_db_format(position)
            asset_id = db_position['asset']
            proxy_wallet = db_position['proxy_wallet']
            
            existing = supabase.table(TABLE_NAME).select("*").eq(
                "asset", asset_id
            ).eq(
                "proxy_wallet", proxy_wallet
            ).execute()
            
            if not existing.data or len(existing.data) == 0:
                supabase.table(TABLE_NAME).insert(db_position).execute()
                success_count += 1
                logger.info(f"➕ New position inserted: {db_position['title'][:50]}")
            else:
                old_data = existing.data[0]
                fields_to_compare = ['size']
                
                has_changes = False
                for field in fields_to_compare:
                    old_val = old_data.get(field)
                    new_val = db_position.get(field)
                    
                    if isinstance(old_val, (int, float)) and isinstance(new_val, (int, float)):
                        if abs(old_val - new_val) > 0.1:
                            has_changes = True
                            break
                    elif old_val != new_val:
                        has_changes = True
                        break
                
                if has_changes:
                    supabase.table(TABLE_NAME).update(db_position).eq(
                        "asset", asset_id
                    ).eq(
                        "proxy_wallet", proxy_wallet
                    ).execute()
                    success_count += 1
                    logger.info(f"🔄 Position updated: {db_position['title'][:50]}")
                else:
                    skipped_count += 1
                    
        except Exception as e:
            error_count += 1
            logger.error(f"❌ Error in position {idx}/{len(positions)}: {e}")
    
    logger.info(f"✅ Summary: {success_count} inserted/updated, {skipped_count} skipped, {error_count} errors")
    return success_count

def print_positions_readable(positions: list):
    if not positions:
        logger.warning("No positions found.")
        return
    for idx, pos in enumerate(positions, 1):
        logger.info(f"Position #{idx}: {pos.get('title')} | Outcome: {pos.get('outcome')} | Value: ${pos.get('currentValue', 0)}")

if __name__ == '__main__':
    user = config.TRADER_WALLET
    positions = fetch_player_positions(user_address=user)
    if positions:
        insert_player_positions_batch(positions)
        print_positions_readable(positions)
