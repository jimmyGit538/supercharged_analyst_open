---
name: python-data-extraction
description: >
  Python data extraction patterns and conventions. Auto-invoke when writing
  Python to extract data from REST APIs or SaaS platforms (Salesforce, Stripe,
  etc.), when managing API credentials via Secret Manager or .env files, when
  implementing incremental/new-data-only extraction with watermarks or cursors,
  or when writing data to BigQuery after extraction. Do NOT load for general
  Python tasks unrelated to data extraction or ingestion.
---

# Python Data Extraction — Standards & Patterns

## 1. Project Structure

Each data source gets its own isolated directory under `01_extraction/`. There
is no shared extractor library — each source is self-contained.

```
01_extraction/
├── salesforce/
│   ├── main.py           # entrypoint — extract and load to BigQuery raw
│   ├── requirements.txt
│   └── Dockerfile
├── stripe/
│   ├── main.py
│   ├── requirements.txt
│   └── Dockerfile
└── <source>/             # one directory per SaaS system or data source
    ├── main.py
    ├── requirements.txt
    └── Dockerfile
```

Each `main.py` runs as a Cloud Run Job — it executes to completion and exits.
No HTTP server or Flask entrypoint is needed.

---

## 2. Dockerfile

Use this standard template for every extractor (from CLAUDE.md):

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY main.py .
CMD ["python", "main.py"]
```

---

## 3. Environment & Credentials

**Local development:** load secrets from `.env` via `python-dotenv`.
**Cloud Run Jobs:** secrets are mounted from **GCP Secret Manager** as
environment variables — `load_dotenv()` is a no-op when vars are already set,
so no code changes are needed between environments.

Never commit `.env`. Never hardcode credentials.

```python
# .env.example  (commit this — placeholders only)
SALESFORCE_USERNAME=
SALESFORCE_PASSWORD=
SALESFORCE_SECURITY_TOKEN=
SALESFORCE_DOMAIN=login
STRIPE_API_KEY=
MY_API_BASE_URL=https://api.example.com
MY_API_KEY=
GCP_PROJECT_ID=
BQ_DATASET=raw
```

```python
# main.py — credential loading
from dotenv import load_dotenv
import os

load_dotenv()  # no-op in Cloud Run; reads .env locally

SALESFORCE_USERNAME = os.getenv("SALESFORCE_USERNAME")
if not SALESFORCE_USERNAME:
    raise EnvironmentError("SALESFORCE_USERNAME is not set")
```

**Rules:**
- Validate required vars at startup; fail fast with a clear message
- Add `.env` to `.gitignore`
- In Cloud Run Jobs, mount secrets via Secret Manager — never bake `.env` into
  the image

```bash
# Store a secret in Secret Manager
gcloud secrets create STRIPE_API_KEY --replication-policy="automatic"
echo -n "sk_live_..." | gcloud secrets versions add STRIPE_API_KEY --data-file=-

# Mount secrets as env vars when creating the Cloud Run Job
gcloud run jobs update stripe-extractor \
  --update-secrets=STRIPE_API_KEY=STRIPE_API_KEY:latest \
  --update-secrets=GCP_PROJECT_ID=GCP_PROJECT_ID:latest
```

---

## 4. Incremental Extraction — New Data Only

### Watermark Strategy (timestamp-based)
Best for: Salesforce, most REST APIs with `updated_at` or `created_at` fields.

Store the watermark in BigQuery or a GCS object so it persists across Cloud Run
Job executions (Cloud Run Jobs have no local state between runs).

```python
# Watermark stored as a GCS JSON file
from google.cloud import storage
import json, os

def load_watermark(source_key: str, default: str = "1970-01-01T00:00:00Z") -> str:
    client = storage.Client()
    bucket = client.bucket(os.getenv("WATERMARK_BUCKET"))
    blob = bucket.blob(f"watermarks/{source_key}.json")
    if not blob.exists():
        return default
    return json.loads(blob.download_as_text()).get("last_extracted", default)

def save_watermark(source_key: str, new_ts: str):
    client = storage.Client()
    bucket = client.bucket(os.getenv("WATERMARK_BUCKET"))
    blob = bucket.blob(f"watermarks/{source_key}.json")
    blob.upload_from_string(json.dumps({"last_extracted": new_ts}))
```

### Cursor Strategy (ID/offset-based)
Best for: Stripe (`starting_after`), paginated REST APIs.

```python
def fetch_stripe_charges(after_cursor: str | None = None) -> list[dict]:
    import stripe
    stripe.api_key = os.getenv("STRIPE_API_KEY")

    params = {"limit": 100}
    if after_cursor:
        params["starting_after"] = after_cursor

    all_charges = []
    while True:
        page = stripe.Charge.list(**params)
        all_charges.extend(page.data)
        if not page.has_more:
            break
        params["starting_after"] = page.data[-1].id

    return all_charges
```

### Choosing a Strategy Per Source

| Source | Recommended Strategy | Field / Param |
|---|---|---|
| Salesforce | Timestamp watermark | `LastModifiedDate >= :watermark` |
| Stripe | Cursor | `starting_after` on list endpoints |
| Generic REST API | Timestamp or cursor | Depends on API docs |

---

## 5. BigQuery Loader

All extractors write to the `raw` BigQuery dataset. Use
`google-cloud-bigquery` — not psycopg2 or any SQL database.

Apply **column pruning** and **`maximum_bytes_billed`** on all queries per
project cost-control rules.

```python
# BigQuery upsert (merge) pattern
from google.cloud import bigquery
import os

def load_to_bigquery(records: list[dict], table_id: str):
    """
    table_id format: "project.dataset.table"
    e.g. "my-project.raw.salesforce_contacts"
    """
    if not records:
        print("[bq] No records to load.")
        return

    client = bigquery.Client()
    errors = client.insert_rows_json(table_id, records)
    if errors:
        raise RuntimeError(f"[bq] Insert errors: {errors}")
    print(f"[bq] Loaded {len(records)} rows into {table_id}")


def get_bq_table_id(source: str) -> str:
    project = os.getenv("GCP_PROJECT_ID")
    dataset = os.getenv("BQ_DATASET", "raw")
    return f"{project}.{dataset}.{source}"
```

For large volumes or schema evolution, prefer `load_table_from_json` with a
write disposition of `WRITE_APPEND`:

```python
def append_to_bigquery(records: list[dict], table_id: str, schema: list):
    client = bigquery.Client()
    job_config = bigquery.LoadJobConfig(
        schema=schema,
        write_disposition="WRITE_APPEND",
    )
    job = client.load_table_from_json(records, table_id, job_config=job_config)
    job.result()  # wait for completion
    print(f"[bq] Appended {len(records)} rows into {table_id}")
```

---

## 6. Salesforce Extractor — `main.py` Template

```python
# 01_extraction/salesforce/main.py
import os
from dotenv import load_dotenv
from simple_salesforce import Salesforce
from google.cloud import bigquery

load_dotenv()

SOURCE_KEY = "salesforce_contacts"
BQ_TABLE = f"{os.getenv('GCP_PROJECT_ID')}.raw.{SOURCE_KEY}"

SF_OBJECT = "Contact"
SF_FIELDS = ["Id", "Name", "Email", "LastModifiedDate"]


def extract(watermark: str) -> list[dict]:
    sf = Salesforce(
        username=os.getenv("SALESFORCE_USERNAME"),
        password=os.getenv("SALESFORCE_PASSWORD"),
        security_token=os.getenv("SALESFORCE_SECURITY_TOKEN"),
        domain=os.getenv("SALESFORCE_DOMAIN", "login"),
    )
    field_list = ", ".join(SF_FIELDS)
    query = (
        f"SELECT {field_list} FROM {SF_OBJECT} "
        f"WHERE LastModifiedDate >= {watermark} "
        f"ORDER BY LastModifiedDate ASC"
    )
    result = sf.query_all(query)
    records = result["records"]
    return [{k: v for k, v in r.items() if k != "attributes"} for r in records]


def load(records: list[dict]):
    if not records:
        return
    client = bigquery.Client()
    errors = client.insert_rows_json(BQ_TABLE, records)
    if errors:
        raise RuntimeError(f"BigQuery insert errors: {errors}")
    print(f"Loaded {len(records)} rows into {BQ_TABLE}")


def main():
    watermark = "1970-01-01T00:00:00Z"  # replace with watermark store lookup
    records = extract(watermark)
    load(records)
    if records:
        new_watermark = records[-1]["LastModifiedDate"]
        print(f"New watermark: {new_watermark}")  # persist this


if __name__ == "__main__":
    main()
```

---

## 7. Generic REST API Extractor — `main.py` Template

```python
# 01_extraction/<source>/main.py
import os
import requests
from dotenv import load_dotenv
from google.cloud import bigquery

load_dotenv()

SOURCE_KEY = "my_api_records"
BQ_TABLE = f"{os.getenv('GCP_PROJECT_ID')}.raw.{SOURCE_KEY}"
BASE_URL = os.getenv("MY_API_BASE_URL")


def extract(watermark: str) -> list[dict]:
    headers = {"Authorization": f"Bearer {os.getenv('MY_API_KEY')}"}
    params = {"updated_after": watermark, "limit": 200}
    records = []

    while True:
        response = requests.get(f"{BASE_URL}/records", headers=headers, params=params)
        response.raise_for_status()
        page = response.json()
        batch = page.get("data", [])
        records.extend(batch)

        next_cursor = page.get("next_cursor")
        if not next_cursor or not batch:
            break
        params["cursor"] = next_cursor

    return records


def load(records: list[dict]):
    if not records:
        return
    client = bigquery.Client()
    errors = client.insert_rows_json(BQ_TABLE, records)
    if errors:
        raise RuntimeError(f"BigQuery insert errors: {errors}")
    print(f"Loaded {len(records)} rows into {BQ_TABLE}")


def main():
    watermark = "1970-01-01T00:00:00Z"  # replace with watermark store lookup
    records = extract(watermark)
    load(records)


if __name__ == "__main__":
    main()
```

---

## 8. Scheduling — Cloud Run Jobs + Cloud Scheduler

Each extractor runs as a **Cloud Run Job** (not a Cloud Run Service). The job
executes `main.py` to completion and exits — no HTTP server needed.

### Architecture

```
Cloud Scheduler (cron) ──── triggers ────▶ Cloud Run Job
                                                │
                                                ├── loads secrets from Secret Manager
                                                ├── extracts from source API
                                                └── writes to BigQuery raw dataset
```

### Create and deploy the Cloud Run Job

```bash
# Build and push container to Artifact Registry
gcloud builds submit \
  --tag us-central1-docker.pkg.dev/PROJECT_ID/data-extractors/salesforce:latest \
  01_extraction/salesforce/

# Create the Cloud Run Job
gcloud run jobs create salesforce-extractor \
  --image us-central1-docker.pkg.dev/PROJECT_ID/data-extractors/salesforce:latest \
  --region us-central1 \
  --service-account extractor-sa@PROJECT_ID.iam.gserviceaccount.com \
  --update-secrets=SALESFORCE_USERNAME=SALESFORCE_USERNAME:latest \
  --update-secrets=SALESFORCE_PASSWORD=SALESFORCE_PASSWORD:latest \
  --update-secrets=SALESFORCE_SECURITY_TOKEN=SALESFORCE_SECURITY_TOKEN:latest \
  --update-secrets=GCP_PROJECT_ID=GCP_PROJECT_ID:latest \
  --memory 512Mi \
  --task-timeout 3600
```

### Schedule with Cloud Scheduler

```bash
# Daily at 2am UTC
gcloud scheduler jobs create http salesforce-extractor-daily \
  --schedule="0 2 * * *" \
  --uri="https://us-central1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/PROJECT_ID/jobs/salesforce-extractor:run" \
  --http-method=POST \
  --oauth-service-account-email=scheduler-sa@PROJECT_ID.iam.gserviceaccount.com \
  --time-zone="UTC"
```

### IAM — required permissions

```bash
# Allow Cloud Scheduler SA to trigger the Cloud Run Job
gcloud projects add-iam-policy-binding PROJECT_ID \
  --member="serviceAccount:scheduler-sa@PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/run.invoker"

# Allow Cloud Run Job SA to write to BigQuery and read secrets
gcloud projects add-iam-policy-binding PROJECT_ID \
  --member="serviceAccount:extractor-sa@PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/bigquery.dataEditor"

gcloud projects add-iam-policy-binding PROJECT_ID \
  --member="serviceAccount:extractor-sa@PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

### Schedule reference

| Cadence | Cron expression |
|---|---|
| Every hour | `0 * * * *` |
| Daily at 2am UTC | `0 2 * * *` |
| Daily at midnight | `0 0 * * *` |
| Every 6 hours | `0 */6 * * *` |
| Weekdays at 7am | `0 7 * * 1-5` |

---

## 9. Required Packages

Adjust per extractor — only include what the source needs.

```
# requirements.txt (Salesforce example)
python-dotenv
simple-salesforce
google-cloud-bigquery
google-cloud-storage   # if using GCS for watermark state
```

```
# requirements.txt (generic REST API example)
python-dotenv
requests
google-cloud-bigquery
google-cloud-storage
```

---

## Error Handling Rules

- Validate all required environment variables at startup; fail fast
- Raise exceptions on API errors — do not silently continue
- Do not update the watermark if extraction or load fails (preserves retry from last good state)
- Log the source name and record count at each stage for Cloud Logging observability
