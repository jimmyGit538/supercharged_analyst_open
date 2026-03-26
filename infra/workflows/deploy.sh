#!/usr/bin/env bash
# Deploy (or redeploy) the indices_pipeline Cloud Workflow and wire Cloud Scheduler.
#
# Prerequisites:
#   - infra/setup.sh has been run (APIs enabled, SAs created)
#   - Both Cloud Run Jobs already exist:
#       * indices-extract-daily
#       * indices-transform-daily
#   - gcloud auth login && gcloud config set project YOUR_PROJECT_ID
#
# Usage:
#   export PROJECT_ID="my-project-123"
#   export REGION="us-central1"
#   bash infra/workflows/deploy.sh

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-YOUR_GCP_PROJECT_ID}"
REGION="${REGION:-YOUR_REGION}"
SCHEDULE="${SCHEDULE:-0 6 * * *}"   # 06:00 UTC daily — adjust to run after market close in your TZ

if [[ "$PROJECT_ID" == YOUR_* || "$REGION" == YOUR_* ]]; then
  echo "ERROR: Set PROJECT_ID and REGION before running." >&2
  echo "  export PROJECT_ID=my-project-123" >&2
  echo "  export REGION=us-central1" >&2
  exit 1
fi

WORKFLOW_NAME="indices-pipeline"
WORKFLOW_SA="workflow-runner@${PROJECT_ID}.iam.gserviceaccount.com"
SCHEDULER_JOB="indices-pipeline-daily"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "Project : $PROJECT_ID"
echo "Region  : $REGION"
echo "Schedule: $SCHEDULE (UTC)"

# ── Enable Workflows API (idempotent) ─────────────────────────────────────────
gcloud services enable workflows.googleapis.com --project="$PROJECT_ID"
gcloud services enable cloudscheduler.googleapis.com --project="$PROJECT_ID"

# ── Service account for the workflow ─────────────────────────────────────────
# This SA needs permission to invoke Cloud Run Jobs.
gcloud iam service-accounts create workflow-runner \
  --display-name="Cloud Workflows Runner" \
  --project="$PROJECT_ID" \
  || echo "SA 'workflow-runner' already exists — skipping"

# Allow the workflow SA to invoke Cloud Run Jobs and poll operation status
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${WORKFLOW_SA}" \
  --role="roles/run.invoker"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${WORKFLOW_SA}" \
  --role="roles/run.viewer"

# ── Deploy the workflow ───────────────────────────────────────────────────────
gcloud workflows deploy "$WORKFLOW_NAME" \
  --source="${SCRIPT_DIR}/indices_pipeline.yaml" \
  --location="$REGION" \
  --service-account="$WORKFLOW_SA" \
  --project="$PROJECT_ID"

echo "Workflow '${WORKFLOW_NAME}' deployed."

# ── Cloud Scheduler → Workflow ────────────────────────────────────────────────
WORKFLOW_RESOURCE="projects/${PROJECT_ID}/locations/${REGION}/workflows/${WORKFLOW_NAME}"

# Scheduler SA needs permission to trigger workflows
SCHEDULER_SA="scheduler-runner@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud iam service-accounts create scheduler-runner \
  --display-name="Cloud Scheduler Runner" \
  --project="$PROJECT_ID" \
  || echo "SA 'scheduler-runner' already exists — skipping"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${SCHEDULER_SA}" \
  --role="roles/workflows.invoker"

# Create or update the scheduler job
if gcloud scheduler jobs describe "$SCHEDULER_JOB" \
      --location="$REGION" \
      --project="$PROJECT_ID" &>/dev/null; then
  gcloud scheduler jobs update http "$SCHEDULER_JOB" \
    --location="$REGION" \
    --schedule="$SCHEDULE" \
    --time-zone="UTC" \
    --uri="https://workflowexecutions.googleapis.com/v1/${WORKFLOW_RESOURCE}/executions" \
    --message-body="{\"argument\": \"{\\\"region\\\": \\\"${REGION}\\\"}\"}" \
    --oauth-service-account-email="$SCHEDULER_SA" \
    --project="$PROJECT_ID"
  echo "Scheduler job '${SCHEDULER_JOB}' updated."
else
  gcloud scheduler jobs create http "$SCHEDULER_JOB" \
    --location="$REGION" \
    --schedule="$SCHEDULE" \
    --time-zone="UTC" \
    --uri="https://workflowexecutions.googleapis.com/v1/${WORKFLOW_RESOURCE}/executions" \
    --message-body="{\"argument\": \"{\\\"region\\\": \\\"${REGION}\\\"}\"}" \
    --oauth-service-account-email="$SCHEDULER_SA" \
    --project="$PROJECT_ID"
  echo "Scheduler job '${SCHEDULER_JOB}' created."
fi

echo ""
echo "══════════════════════════════════════════════════════════════════"
echo "Done. Pipeline runs daily at: ${SCHEDULE} UTC"
echo ""
echo "To test immediately:"
echo "  gcloud workflows run ${WORKFLOW_NAME} --location=${REGION} --project=${PROJECT_ID}"
echo ""
echo "To check execution status:"
echo "  gcloud workflows executions list ${WORKFLOW_NAME} --location=${REGION} --project=${PROJECT_ID}"
echo "══════════════════════════════════════════════════════════════════"
