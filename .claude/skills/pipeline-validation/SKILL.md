---
name: pipeline-validation
description: >
  End-to-end pipeline validation guide for this repo. Auto-invoke after deploying
  a new data source (terraform apply + image push), after a Cloud Run Job or Cloud
  Workflow execution, or when verifying that data landed correctly in BigQuery.
  Do NOT load for general GCP or dbt questions unrelated to validating this pipeline.
---

# Pipeline Validation

CI passing proves code is syntactically valid. It does not prove the pipeline runs.
Run these steps after every new source deployment to confirm data flows end-to-end.

Set your environment before starting:
```bash
export PROJECT_ID="your-gcp-project-id"
export REGION="us-central1"   # or your configured region
export SOURCE="your-source"   # e.g. "fred", "coinmarketcap"
```

---

## Step 1 — Confirm Cloud Run Jobs exist

```bash
gcloud run jobs list --region $REGION --project $PROJECT_ID \
  --filter "name~$SOURCE"
```

Expected: 5 jobs listed, one per stage:
```
${SOURCE}-extract-daily
${SOURCE}-dbt-stg-warehouse-daily
${SOURCE}-dbt-warehouse-daily
${SOURCE}-dbt-stg-marts-daily
${SOURCE}-dbt-mart-daily
```

If jobs are missing: `terraform plan` to check for drift, then `terraform apply`.

---

## Step 2 — Trigger the extraction job manually

```bash
gcloud run jobs execute ${SOURCE}-extract-daily \
  --region $REGION --project $PROJECT_ID --wait
```

`--wait` blocks until the job completes and prints success or failure. A timeout or non-zero exit means the job failed — proceed to Step 3 to read logs.

---

## Step 3 — Check execution logs

```bash
gcloud logging read \
  "resource.type=cloud_run_job AND resource.labels.job_name=${SOURCE}-extract-daily" \
  --project $PROJECT_ID --limit 50 --format "value(textPayload)"
```

**Success looks like:** rows-written log line, no Python tracebacks, exit code 0.

**Silent failure looks like:** job shows as "succeeded" but 0 rows written — check for:
- API returning empty results (rate limit, bad date range, no new data)
- BigQuery write silently skipped due to conditional logic in `main.py`

**Common post-deploy failures:**

| Symptom | Likely cause | Fix |
|---|---|---|
| `PermissionDenied` on Secret Manager | Secret exists but `extraction-runner` SA lacks `secretmanager.secretAccessor` | Check `iam.tf`, re-apply Terraform |
| `Secret not found` | Secret not created in Secret Manager | Create via `gcloud secrets create` and add the value |
| `403` on BigQuery write | `extraction-runner` SA lacks `bigquery.dataEditor` on `raw` dataset | Check dataset access in `infra/setup.sh` and re-run |
| IAM error immediately after `terraform apply` | IAM propagation delay (up to 60s) | Wait 60 seconds and retry |

---

## Step 4 — Confirm rows landed in BigQuery

```sql
-- Run in BigQuery console or via bq CLI
SELECT COUNT(*) AS row_count, MAX(_ingested_at) AS latest_ingestion
FROM `YOUR_PROJECT_ID.raw.<source>_<entity>`
```

Replace `<source>_<entity>` with the table name written by your extraction job.

Via CLI:
```bash
bq query --use_legacy_sql=false --project_id $PROJECT_ID \
  "SELECT COUNT(*) FROM \`${PROJECT_ID}.raw.${SOURCE}_raw\`"
```

Expected: row count > 0, `latest_ingestion` is within the last few minutes.

---

## Step 5 — Run dbt models manually

```bash
cd 02_dbt

# Run all models for this source
dbt run --select ${SOURCE}

# Run tests
dbt test --select ${SOURCE}
```

Success: all models show `OK` status, all tests pass.

Common dbt failures after a new source:

| Error | Cause | Fix |
|---|---|---|
| `Relation not found` | Raw table doesn't exist yet | Complete Steps 2–4 first |
| `Column not found` | Schema mismatch between raw data and staging model | Update the staging model columns to match actual raw schema |
| `dbt test failed` | Data quality issue (nulls, duplicates) | Inspect the raw data; adjust test severity or fix extraction |

---

## Step 6 — Confirm mart rows exist

```sql
SELECT COUNT(*) AS row_count
FROM `YOUR_PROJECT_ID.marts.fct_<name>`
```

If row count is 0 but dbt run succeeded: check whether the mart model's `WHERE` or `JOIN` conditions are filtering everything out. Run the SQL directly in BigQuery to debug.

---

## Step 7 — Validate the full Cloud Workflow (optional but recommended)

Trigger the workflow that runs all 5 stages in sequence:

```bash
gcloud workflows execute ${SOURCE}-pipeline \
  --location $REGION --project $PROJECT_ID
```

Check the execution result:
```bash
gcloud workflows executions list ${SOURCE}-pipeline \
  --location $REGION --project $PROJECT_ID --limit 1
```

A `SUCCEEDED` state confirms the full pipeline runs end-to-end without manual intervention.
