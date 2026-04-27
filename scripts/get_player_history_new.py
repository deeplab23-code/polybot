import requests
from supabase import create_client, Client
from datetime import datetime
from config import get_config

config = get_config()

url: str = config.SUPABASE_URL
key: str = config.SUPABASE_KEY
supabase: Client = create_client(url, key)

API_URL = "https://data-api.polymarket.com/activity"
MAX_LIMIT = 500
TABLE_NAME = config.TABLE_NAME_TRADES

# Wallets que ya pasaron por el warm-up inicial
_initialized_wallets: set = set()


def transform_activity_to_db_format(activity: dict) -> dict:
    activity_datetime = datetime.fromtimestamp(activity['timestamp'])
    return {
        'proxy_wallet': activity.get('proxyWallet'),
        'timestamp': activity.get('timestamp'),
        'activity_datetime': activity_datetime.isoformat(),
        'condition_id': activity.get('conditionId'),
        'type': activity.get('type'),
        'size': activity.get('size'),
        'usdc_size': activity.get('usdcSize'),
        'transaction_hash': activity.get('transactionHash'),
        'price': activity.get('price'),
        'asset': activity.get('asset'),
        'side': activity.get('side'),
        'outcome_index': activity.get('outcomeIndex'),
        'title': activity.get('title'),
        'slug': activity.get('slug'),
        'icon': activity.get('icon'),
        'event_slug': activity.get('eventSlug'),
        'outcome': activity.get('outcome'),
        'trader_name': activity.get('name'),
        'pseudonym': activity.get('pseudonym'),
        'bio': activity.get('bio'),
        'profile_image': activity.get('profileImage'),
        'profile_image_optimized': activity.get('profileImageOptimized'),
        'end_date': activity.get('endDate'),
    }


def fetch_activities(user_address: str, limit: int = 500, offset: int = 0):
    resp = requests.get(API_URL, params={
        "user": user_address,
        "limit": str(limit),
        "offset": str(offset),
        "sortBy": "TIMESTAMP",
        "sortDirection": "DESC",
    })
    data = resp.json()
    db_activities = [transform_activity_to_db_format(activity) for activity in data]
    print('===============================================')
    print('fetching activities from', user_address)
    print('db_activities length', len(db_activities))
    print('===============================================')
    return db_activities


def _get_existing_hashes(hashes: list) -> set:
    existing = set()
    chunk_size = 100
    for i in range(0, len(hashes), chunk_size):
        chunk = hashes[i:i + chunk_size]
        result = supabase.table(TABLE_NAME)\
            .select("transaction_hash")\
            .in_("transaction_hash", chunk)\
            .execute()
        for r in result.data:
            existing.add(r['transaction_hash'])
    return existing


def _insert_as_seen(activities: list) -> None:
    """Inserta actividades en Supabase sin retornarlas para ejecución."""
    for activity in activities:
        try:
            supabase.table(TABLE_NAME).insert(activity).execute()
        except Exception as e:
            # duplicate key = ya existe, ignorar
            if "duplicate" not in str(e).lower() and "23505" not in str(e):
                print(f"Error inserting activity: {e}")


def get_new_activities(activities: list, wallet: str = None) -> list:
    """
    Primera vez que se llama para una wallet: inserta todo como "visto" y retorna vacío.
    Siguientes veces: retorna solo las realmente nuevas para ejecutar.
    """
    if not activities:
        return []

    hashes = [a['transaction_hash'] for a in activities if a.get('transaction_hash')]
    if not hashes:
        return []

    existing_hashes = _get_existing_hashes(hashes)
    new_ones = [a for a in activities if a.get('transaction_hash') not in existing_hashes]

    if not new_ones:
        return []

    # Si esta wallet no fue inicializada todavía, marcar todo como visto sin ejecutar
    if wallet and wallet not in _initialized_wallets:
        print(f"🔄 Warm-up for {wallet[:10]}... — marking {len(new_ones)} historical trades as seen (not executing)")
        _insert_as_seen(new_ones)
        _initialized_wallets.add(wallet)
        return []

    # Wallet ya inicializada — estas son trades realmente nuevas
    _insert_as_seen(new_ones)
    return new_ones


def insert_activities_batch(activities: list):
    if not activities:
        return 0
    hashes = [a['transaction_hash'] for a in activities if a.get('transaction_hash')]
    if not hashes:
        return 0
    existing_hashes = _get_existing_hashes(hashes)
    new_activities = [a for a in activities if a.get('transaction_hash') not in existing_hashes]
    if not new_activities:
        return 0
    print(f"🆕 {len(new_activities)} new activities detected — inserting...")
    inserted = 0
    for activity in new_activities:
        try:
            supabase.table(TABLE_NAME).insert(activity).execute()
            inserted += 1
        except Exception as e:
            print(f"Error inserting activity: {e}")
    print(f"✅ Inserted {inserted} new activities")
    return inserted


if __name__ == "__main__":
    user_address = input("Enter the user address: ")
    activities = fetch_activities(user_address)
    success_count = insert_activities_batch(activities)
    print(f"Success count: {success_count}")
