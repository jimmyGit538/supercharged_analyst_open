import os
import requests
from datetime import date, datetime, timedelta, timezone
from dotenv import load_dotenv
from google.cloud import bigquery

load_dotenv()

# S&P 500 proxy (IVV ETF), Nasdaq Composite (ONEQ ETF), Dow Jones proxy (DIA ETF)
SYMBOLS = ["IVV", "ONEQ", "DIA"]
INTERVAL = "1day"
BASE_URL = "https://api.twelvedata.com"
BQ_PROJECT = os.getenv("BQ_PROJECT_EXTRACTION")
BQ_DATASET = os.getenv("BQ_DATASET_EXTRACTION", "raw")
BQ_TABLE = f"{BQ_PROJECT}.{BQ_DATASET}.twelvedata_indices_daily"
TWELVEDATA_API_KEY = os.getenv("TWELVEDATA_API_KEY")

if not TWELVEDATA_API_KEY:
    raise EnvironmentError("TWELVEDATA_API_KEY is not set")
if not BQ_PROJECT:
    raise EnvironmentError("BQ_PROJECT_EXTRACTION is not set")

SCHEMA = [
    bigquery.SchemaField("date", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("symbol", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("open", "FLOAT64"),
    bigquery.SchemaField("high", "FLOAT64"),
    bigquery.SchemaField("low", "FLOAT64"),
    bigquery.SchemaField("close", "FLOAT64"),
    bigquery.SchemaField("volume", "INT64"),
    bigquery.SchemaField("extracted_at", "TIMESTAMP", mode="REQUIRED"),
]


def get_watermark(client: bigquery.Client, symbol: str) -> str | None:
    """Return the latest date already in BigQuery for this symbol, or None for a full load."""
    query = f"""
        SELECT MAX(date) AS max_date
        FROM `{BQ_TABLE}`
        WHERE symbol = '{symbol}'
    """
    try:
        result = client.query(
            query,
            job_config=bigquery.QueryJobConfig(maximum_bytes_billed=10 * 1024 * 1024),
        ).result()
        row = next(iter(result))
        return str(row.max_date) if row.max_date else None
    except Exception:
        return None  # table doesn't exist yet — full load


def extract(symbol: str, start_date: str | None) -> list[dict]:
    params = {
        "symbol": symbol,
        "interval": INTERVAL,
        "outputsize": 5000,
        "apikey": TWELVEDATA_API_KEY,
        "format": "JSON",
    }
    if start_date:
        next_day = str(date.fromisoformat(start_date) + timedelta(days=1))
        params["start_date"] = next_day

    response = requests.get(f"{BASE_URL}/time_series", params=params, timeout=30)
    response.raise_for_status()
    data = response.json()

    if data.get("status") == "error":
        msg = data.get("message", "")
        if "No data is available" in msg:
            print(f"[extract] {symbol}: no new data available — non-trading period.")
            return []
        raise RuntimeError(f"Twelvedata API error ({symbol}): {msg}")

    values = data.get("values", [])
    print(f"[extract] {symbol}: fetched {len(values)} rows")
    return values


def transform(symbol: str, values: list[dict]) -> list[dict]:
    extracted_at = datetime.now(timezone.utc).isoformat()
    return [
        {
            "date": row["datetime"],
            "symbol": symbol,
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
            "volume": int(row["volume"]),
            "extracted_at": extracted_at,
        }
        for row in values
    ]


def load(client: bigquery.Client, records: list[dict]) -> None:
    if not records:
        print("[load] No new records to load.")
        return

    job_config = bigquery.LoadJobConfig(
        schema=SCHEMA,
        write_disposition="WRITE_APPEND",
    )
    job = client.load_table_from_json(records, BQ_TABLE, job_config=job_config)
    job.result()
    print(f"[load] Appended {len(records)} rows into {BQ_TABLE}")


def main():
    client = bigquery.Client(project=BQ_PROJECT)
    all_records = []

    for symbol in SYMBOLS:
        watermark = get_watermark(client, symbol)
        print(f"[watermark] {symbol}: last loaded date = {watermark or 'none — full load'}")

        values = extract(symbol, start_date=watermark)
        if not values:
            continue

        records = transform(symbol, values)
        all_records.extend(records)
        print(f"[transform] {symbol}: latest date = {records[0]['date']}")

    load(client, all_records)
    print(f"[main] Done. Total rows loaded: {len(all_records)}")


if __name__ == "__main__":
    main()
