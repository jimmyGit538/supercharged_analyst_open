import json
import os
import sys
import time
from datetime import date, datetime, timedelta, timezone

import requests
from dotenv import load_dotenv
from google.cloud import bigquery

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()

BASE_URL = "https://pro-api.coinmarketcap.com/v1"
CMC_API_KEY = os.getenv("COINMARKETCAP_API_KEY")
BQ_PROJECT = os.getenv("BQ_PROJECT_EXTRACTION")
BQ_DATASET = os.getenv("BQ_DATASET_EXTRACTION", "raw")

if not CMC_API_KEY:
    raise EnvironmentError("COINMARKETCAP_API_KEY is not set")
if not BQ_PROJECT:
    raise EnvironmentError("BQ_PROJECT_EXTRACTION is not set")

HEADERS = {"X-CMC_PRO_API_KEY": CMC_API_KEY, "Accept": "application/json"}

BQ_CATEGORIES_TABLE = f"{BQ_PROJECT}.{BQ_DATASET}.coinmarketcap_categories"
BQ_CATEGORY_COINS_TABLE = f"{BQ_PROJECT}.{BQ_DATASET}.coinmarketcap_category_coins"
BQ_METADATA_TABLE = f"{BQ_PROJECT}.{BQ_DATASET}.coinmarketcap_coin_metadata"
BQ_QUOTES_TABLE = f"{BQ_PROJECT}.{BQ_DATASET}.coinmarketcap_quotes_daily"

HISTORICAL_START_DAYS = 364  # Hobbyist plan: max 12 months lookback
METADATA_BATCH_SIZE = 100

CATEGORIES_SCHEMA = [
    bigquery.SchemaField("id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("name", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("num_tokens", "INT64"),
    bigquery.SchemaField("market_cap_usd", "FLOAT64"),
    bigquery.SchemaField("market_cap_change", "FLOAT64"),
    bigquery.SchemaField("volume_usd", "FLOAT64"),
    bigquery.SchemaField("volume_change", "FLOAT64"),
    bigquery.SchemaField("last_updated", "STRING"),
    bigquery.SchemaField("extracted_at", "TIMESTAMP", mode="REQUIRED"),
]

CATEGORY_COINS_SCHEMA = [
    bigquery.SchemaField("category_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("category_name", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("coin_id", "INT64", mode="REQUIRED"),
    bigquery.SchemaField("coin_symbol", "STRING"),
    bigquery.SchemaField("coin_name", "STRING"),
    bigquery.SchemaField("coin_slug", "STRING"),
    bigquery.SchemaField("cmc_rank", "INT64"),
    bigquery.SchemaField("extracted_at", "TIMESTAMP", mode="REQUIRED"),
]

METADATA_SCHEMA = [
    bigquery.SchemaField("coin_id", "INT64", mode="REQUIRED"),
    bigquery.SchemaField("symbol", "STRING"),
    bigquery.SchemaField("name", "STRING"),
    bigquery.SchemaField("slug", "STRING"),
    bigquery.SchemaField("description", "STRING"),
    bigquery.SchemaField("category", "STRING"),
    bigquery.SchemaField("tags", "STRING"),
    bigquery.SchemaField("website", "STRING"),
    bigquery.SchemaField("extracted_at", "TIMESTAMP", mode="REQUIRED"),
]

QUOTES_SCHEMA = [
    bigquery.SchemaField("date", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("coin_id", "INT64", mode="REQUIRED"),
    bigquery.SchemaField("symbol", "STRING"),
    bigquery.SchemaField("name", "STRING"),
    bigquery.SchemaField("price_usd", "FLOAT64"),
    bigquery.SchemaField("volume_24h_usd", "FLOAT64"),
    bigquery.SchemaField("market_cap_usd", "FLOAT64"),
    bigquery.SchemaField("percent_change_1h", "FLOAT64"),
    bigquery.SchemaField("percent_change_24h", "FLOAT64"),
    bigquery.SchemaField("percent_change_7d", "FLOAT64"),
    bigquery.SchemaField("extracted_at", "TIMESTAMP", mode="REQUIRED"),
]


def _get(endpoint: str, params: dict, retries: int = 5) -> dict:
    for attempt in range(retries):
        response = requests.get(f"{BASE_URL}{endpoint}", params=params, headers=HEADERS, timeout=30)
        if response.status_code == 429 or response.status_code >= 500:
            wait = 2 ** attempt * 5
            print(f"[retry] HTTP {response.status_code} on {endpoint} — sleeping {wait}s (attempt {attempt + 1}/{retries})")
            time.sleep(wait)
            continue
        response.raise_for_status()
        data = response.json()
        status = data.get("status", {})
        if status.get("error_code") != 0:
            raise RuntimeError(f"CMC API error ({status.get('error_code')}): {status.get('error_message')}")
        return data
    raise RuntimeError(f"CMC API still failing after {retries} retries on {endpoint}")


def extract_categories() -> tuple[list[dict], list[dict], set[int]]:
    """Return (category_rows, category_coin_rows, unique_coin_ids)."""
    extracted_at = datetime.now(timezone.utc).isoformat()

    data = _get("/cryptocurrency/categories", {"start": 1, "limit": 5000})
    categories = data.get("data", [])
    print(f"[categories] Fetched {len(categories)} categories")

    category_rows = []
    category_coin_rows = []
    unique_coin_ids: set[int] = set()

    for cat in categories:
        category_rows.append({
            "id": str(cat["id"]),
            "name": cat.get("name", ""),
            "num_tokens": cat.get("num_tokens"),
            "market_cap_usd": cat.get("market_cap"),
            "market_cap_change": cat.get("market_cap_change"),
            "volume_usd": cat.get("volume"),
            "volume_change": cat.get("volume_change"),
            "last_updated": cat.get("last_updated"),
            "extracted_at": extracted_at,
        })

        cat_data = _get("/cryptocurrency/category", {"id": cat["id"], "limit": 1000, "start": 1})
        coins = cat_data.get("data", {}).get("coins", [])
        print(f"[categories] {cat.get('name')}: {len(coins)} coins")

        for coin in coins:
            coin_id = coin.get("id")
            if coin_id:
                unique_coin_ids.add(int(coin_id))
                category_coin_rows.append({
                    "category_id": str(cat["id"]),
                    "category_name": cat.get("name", ""),
                    "coin_id": int(coin_id),
                    "coin_symbol": coin.get("symbol"),
                    "coin_name": coin.get("name"),
                    "coin_slug": coin.get("slug"),
                    "cmc_rank": coin.get("cmc_rank"),
                    "extracted_at": extracted_at,
                })

        time.sleep(0.2)

    print(f"[categories] {len(unique_coin_ids)} unique coins across all categories")
    return category_rows, category_coin_rows, unique_coin_ids


def extract_metadata(coin_ids: set[int]) -> list[dict]:
    extracted_at = datetime.now(timezone.utc).isoformat()
    ids_list = list(coin_ids)
    metadata_rows = []

    for i in range(0, len(ids_list), METADATA_BATCH_SIZE):
        batch = ids_list[i : i + METADATA_BATCH_SIZE]
        data = _get("/cryptocurrency/info", {"id": ",".join(str(x) for x in batch)})
        for coin_id_str, info in data.get("data", {}).items():
            urls = info.get("urls", {})
            websites = urls.get("website", [])
            metadata_rows.append({
                "coin_id": int(coin_id_str),
                "symbol": info.get("symbol"),
                "name": info.get("name"),
                "slug": info.get("slug"),
                "description": info.get("description"),
                "category": info.get("category"),
                "tags": json.dumps(info.get("tags", [])),
                "website": websites[0] if websites else None,
                "extracted_at": extracted_at,
            })
        print(f"[metadata] Fetched batch {i // METADATA_BATCH_SIZE + 1}: {len(batch)} coins")
        time.sleep(0.2)

    return metadata_rows


def get_watermark(client: bigquery.Client, coin_id: int) -> str | None:
    query = f"SELECT MAX(date) AS max_date FROM `{BQ_QUOTES_TABLE}` WHERE coin_id = {coin_id}"
    try:
        result = client.query(
            query,
            job_config=bigquery.QueryJobConfig(maximum_bytes_billed=10 * 1024 * 1024),
        ).result()
        row = next(iter(result))
        return str(row.max_date) if row.max_date else None
    except Exception:
        return None


def extract_quotes(client: bigquery.Client, coin_ids: set[int]) -> list[dict]:
    extracted_at = datetime.now(timezone.utc).isoformat()
    today = str(date.today())
    all_rows = []

    for coin_id in coin_ids:
        plan_start = str(date.today() - timedelta(days=HISTORICAL_START_DAYS))
        watermark = get_watermark(client, coin_id)
        if watermark:
            time_start = str(date.fromisoformat(watermark) + timedelta(days=1))
            if time_start >= today:
                continue
        else:
            time_start = plan_start

        try:
            data = _get("/cryptocurrency/quotes/historical", {
                "id": coin_id,
                "time_start": time_start,
                "time_end": today,
                "interval": "daily",
                "convert": "USD",
            })
        except RuntimeError as e:
            print(f"[quotes] coin_id={coin_id}: skipping — {e}")
            time.sleep(0.2)
            continue

        quotes = data.get("data", {}).get("quotes", [])
        symbol = data.get("data", {}).get("symbol")
        name = data.get("data", {}).get("name")

        for q in quotes:
            usd = q.get("quote", {}).get("USD", {})
            row_date = q.get("timestamp", "")[:10]
            all_rows.append({
                "date": row_date,
                "coin_id": coin_id,
                "symbol": symbol,
                "name": name,
                "price_usd": usd.get("price"),
                "volume_24h_usd": usd.get("volume_24h"),
                "market_cap_usd": usd.get("market_cap"),
                "percent_change_1h": usd.get("percent_change_1h"),
                "percent_change_24h": usd.get("percent_change_24h"),
                "percent_change_7d": usd.get("percent_change_7d"),
                "extracted_at": extracted_at,
            })

        print(f"[quotes] coin_id={coin_id} ({symbol}): {len(quotes)} rows from {time_start}")
        time.sleep(0.4)

    return all_rows


def _load_truncate(client: bigquery.Client, records: list[dict], table: str, schema: list) -> None:
    if not records:
        print(f"[load] No records for {table}")
        return
    job_config = bigquery.LoadJobConfig(schema=schema, write_disposition="WRITE_TRUNCATE")
    client.load_table_from_json(records, table, job_config=job_config).result()
    print(f"[load] Truncated and wrote {len(records)} rows → {table}")


def _load_append(client: bigquery.Client, records: list[dict], table: str, schema: list) -> None:
    if not records:
        print(f"[load] No new records for {table}")
        return
    job_config = bigquery.LoadJobConfig(schema=schema, write_disposition="WRITE_APPEND")
    client.load_table_from_json(records, table, job_config=job_config).result()
    print(f"[load] Appended {len(records)} rows → {table}")


def main():
    client = bigquery.Client(project=BQ_PROJECT)

    print("[main] Phase 1: categories")
    category_rows, category_coin_rows, unique_coin_ids = extract_categories()

    print(f"[main] Phase 2: metadata for {len(unique_coin_ids)} coins")
    metadata_rows = extract_metadata(unique_coin_ids)

    print(f"[main] Phase 3: historical quotes for {len(unique_coin_ids)} coins")
    quote_rows = extract_quotes(client, unique_coin_ids)

    print("[main] Phase 4: loading to BigQuery")
    _load_truncate(client, category_rows, BQ_CATEGORIES_TABLE, CATEGORIES_SCHEMA)
    _load_truncate(client, category_coin_rows, BQ_CATEGORY_COINS_TABLE, CATEGORY_COINS_SCHEMA)
    _load_truncate(client, metadata_rows, BQ_METADATA_TABLE, METADATA_SCHEMA)
    _load_append(client, quote_rows, BQ_QUOTES_TABLE, QUOTES_SCHEMA)

    print(
        f"[main] Done. categories={len(category_rows)}, "
        f"category_coins={len(category_coin_rows)}, "
        f"metadata={len(metadata_rows)}, "
        f"quotes={len(quote_rows)}"
    )


if __name__ == "__main__":
    main()
