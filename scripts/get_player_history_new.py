import requests
from supabase import create_client, Client
from datetime import datetime
from config import get_config

# Load configuration
config = get_config()

# config supabase
url: str = config.SUPABASE_URL
key: str = config.SUPABASE_KEY
supabase: Client = create_client(url, key)

# config api
API_URL = "https://data-api.polymarket.com/activity"
MAX_LIMIT = 500  # max limit of the api
TABLE_NAME = config.TABLE_NAME_TRADES


def transform_activity_to_db_format(activity: dict) -> dict:
    """
    Transforms API format to database format
    """
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
    }


def fetch_activities(user_address: str, limit: int = 500, offset: int = 0):
    """
    Fetch activities from the api
    """
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
    """
    Consulta Supabase en chunks de 100 para evitar el límite de .in_()
    """
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


def get_new_activities(activities: list) -> list:
    """
    Devuelve solo las actividades que NO están en Supabase todavía.
    No inserta nada — solo filtra. El insert lo hace insert_activities_batch.
    """
    if not activities:
        return []
    hashes = [a['transaction_hash'] for a in activities if a.get('transaction_hash')]
    if not hashes:
        return []
    existing_hashes = _get_existing_hashes(hashes)
    new_ones = [a for a in activities if a.get('transaction_hash') not in existing_hashes]
    if new_ones:
        # Insertar en Supabase para que no se reprocesen
        for activity in new_ones:
            try:
                supabase.table(TABLE_NAME).insert(activity).execute()
            except Exception as e:
                print(f"Error inserting activity: {e}")
    return new_ones


def insert_activities_batch(activities: list):
    """
    Insert only genuinely new activities.
    Uses INSERT (not upsert) so Supabase Realtime fires correctly.
    """
    if not activities:
        return 0

    hashes = [a['transaction_hash'] for a in activities if a.get('transaction_hash')]
    if not hashes:
        return 0

    existing_hashes = _get_existing_hashes(hashes)

    new_activities = [
        a for a in activities
        if a.get('transaction_hash') not in existing_hashes
    ]

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
