#!/usr/bin/env bash
# create_jobs.sh — Create (or update) all Cloud Run Jobs for the indices pipeline.
#
# Usage:
#   export PROJECT_ID=YOUR_PROJECT_ID
#   export REGION=us-central1
#   bash infra/workflows/create_jobs.sh
#
# Re-running is safe: existing jobs are updated via `gcloud run jobs update`.

set -euo pipefail

: "${PROJECT_ID:?PROJECT_ID must be set}"
: "${REGION:?REGION must be set}"

if [[ "$PROJECT_ID" == "YOUR_PROJECT_ID" || "$REGION" == "YOUR_REGION" ]]; then
  echo "ERROR: replace placeholder values before running." >&2
  exit 1
fi

EXTRACTION_IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/extraction/twelvedata-indices:latest"
DBT_IMAGE="$REGION-docker.pkg.dev/$PROJECT_ID/extraction/dbt-runner:latest"
DBT_SA="dbt-runner@$PROJECT_ID.iam.gserviceaccount.com"
DBT_ENV="BQ_PROJECT=$PROJECT_ID"
EXTRACTION_SA="extraction-runner@$PROJECT_ID.iam.gserviceaccount.com"

# Helper: create or update a Cloud Run Job
upsert_job() {
  local job_name="$1"
  shift
  if gcloud run jobs describe "$job_name" --region "$REGION" --project "$PROJECT_ID" &>/dev/null; then
    echo "Updating $job_name ..."
    gcloud run jobs update "$job_name" --region "$REGION" --project "$PROJECT_ID" "$@"
  else
    echo "Creating $job_name ..."
    gcloud run jobs create "$job_name" --region "$REGION" --project "$PROJECT_ID" "$@"
  fi
}

# ── 1. indices-extract-daily ─────────────────────────────────────────────────
upsert_job "indices-extract-daily" \
  --image "$EXTRACTION_IMAGE" \
  --service-account "$EXTRACTION_SA" \
  --task-timeout 600 \
  --max-retries 1 \
  --set-env-vars="BQ_PROJECT_EXTRACTION=$PROJECT_ID" \
  --set-secrets="TWELVEDATA_API_KEY=TWELVEDATA_API_KEY:latest"

# ── 2. indices-dbt-stg-warehouse-daily ───────────────────────────────────────
# Note: use --args only (no --command) to avoid gcloud resolving /bin/sh as a
# local Windows path. The first arg becomes the executable in the container.
upsert_job "indices-dbt-stg-warehouse-daily" \
  --image "$DBT_IMAGE" \
  --service-account "$DBT_SA" \
  --set-env-vars="$DBT_ENV" \
  --task-timeout 600 \
  --max-retries 1 \
  --command="" \
  --args="sh,-c,dbt run --profiles-dir /app --project-dir /app --target cloudrun --select 1_staging_warehouses"

# ── 3. indices-dbt-warehouse-daily ───────────────────────────────────────────
# dbt seed runs here: wh_indices_metadata is loaded from a CSV seed before
# warehouse models are built.
upsert_job "indices-dbt-warehouse-daily" \
  --image "$DBT_IMAGE" \
  --service-account "$DBT_SA" \
  --set-env-vars="$DBT_ENV" \
  --task-timeout 600 \
  --max-retries 1 \
  --command="" \
  --args="sh,-c,dbt seed --profiles-dir /app --project-dir /app --target cloudrun && dbt run --profiles-dir /app --project-dir /app --target cloudrun --select 2_warehouses"

# ── 4. indices-dbt-stg-marts-daily ───────────────────────────────────────────
upsert_job "indices-dbt-stg-marts-daily" \
  --image "$DBT_IMAGE" \
  --service-account "$DBT_SA" \
  --set-env-vars="$DBT_ENV" \
  --task-timeout 600 \
  --max-retries 1 \
  --command="" \
  --args="sh,-c,dbt run --profiles-dir /app --project-dir /app --target cloudrun --select 3_staging_marts"

# ── 5. indices-dbt-mart-daily ────────────────────────────────────────────────
upsert_job "indices-dbt-mart-daily" \
  --image "$DBT_IMAGE" \
  --service-account "$DBT_SA" \
  --set-env-vars="$DBT_ENV" \
  --task-timeout 600 \
  --max-retries 1 \
  --command="" \
  --args="sh,-c,dbt run --profiles-dir /app --project-dir /app --target cloudrun --select 4_marts"

echo ""
echo "All indices pipeline jobs created/updated."
echo ""
echo "Next steps:"
echo "  1. Run deploy.sh to redeploy the updated workflow."
echo "  2. Trigger the workflow manually and verify all 5 steps succeed."
echo "  3. Once verified, delete the old job:"
echo "     gcloud run jobs delete indices-transform-daily --region $REGION --project $PROJECT_ID"
