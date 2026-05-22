#!/usr/bin/env bash
# import.sh — Import all existing GCP resources into Terraform state.
#
# Prerequisites:
#   1. terraform init has been run
#   2. terraform.tfvars is populated with real values
#   3. gcloud is authenticated with project access
#
# Usage:
#   export PROJECT_ID="my-project-123"
#   export REGION="us-central1"
#   export GITHUB_REPO="org/repo"
#   bash infra/terraform/import.sh

set -euo pipefail

: "${PROJECT_ID:?PROJECT_ID must be set}"
: "${REGION:?REGION must be set}"
: "${GITHUB_REPO:?GITHUB_REPO must be set}"

if [[ "$PROJECT_ID" == "YOUR_"* || "$REGION" == "YOUR_"* ]]; then
  echo "ERROR: replace placeholder values before running." >&2
  exit 1
fi

PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')

cd "$(dirname "$0")"

echo "Importing existing resources into Terraform state..."
echo "Project: $PROJECT_ID ($PROJECT_NUMBER)"
echo "Region:  $REGION"
echo ""

# Helper: import with error handling (skip already-imported resources)
tf_import() {
  local addr="$1"
  local id="$2"
  echo "  Importing: $addr"
  terraform import "$addr" "$id" 2>&1 | grep -v "^$" || true
}

# ── Phase 1: APIs ────────────────────────────────────────────────────────────
echo "Phase 1: APIs"
for api in \
  run.googleapis.com \
  cloudscheduler.googleapis.com \
  workflows.googleapis.com \
  bigquery.googleapis.com \
  artifactregistry.googleapis.com \
  logging.googleapis.com \
  monitoring.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  sts.googleapis.com \
  secretmanager.googleapis.com; do
  tf_import "google_project_service.apis[\"${api}\"]" "${PROJECT_ID}/${api}"
done

# ── Phase 2: Artifact Registry ───────────────────────────────────────────────
echo ""
echo "Phase 2: Artifact Registry"
tf_import "google_artifact_registry_repository.extraction" \
  "projects/${PROJECT_ID}/locations/${REGION}/repositories/extraction"

# ── Phase 3: Service accounts ────────────────────────────────────────────────
echo ""
echo "Phase 3: Service accounts"
tf_import "google_service_account.extraction_runner" \
  "projects/${PROJECT_ID}/serviceAccounts/extraction-runner@${PROJECT_ID}.iam.gserviceaccount.com"
tf_import "google_service_account.dbt_runner" \
  "projects/${PROJECT_ID}/serviceAccounts/dbt-runner@${PROJECT_ID}.iam.gserviceaccount.com"
tf_import "google_service_account.github_actions_ci" \
  "projects/${PROJECT_ID}/serviceAccounts/github-actions-ci@${PROJECT_ID}.iam.gserviceaccount.com"
tf_import "google_service_account.workflow_runner" \
  "projects/${PROJECT_ID}/serviceAccounts/workflow-runner@${PROJECT_ID}.iam.gserviceaccount.com"
tf_import "google_service_account.scheduler_runner" \
  "projects/${PROJECT_ID}/serviceAccounts/scheduler-runner@${PROJECT_ID}.iam.gserviceaccount.com"

# ── Phase 4: Workload Identity Federation ────────────────────────────────────
echo ""
echo "Phase 4: Workload Identity Federation"
tf_import "google_iam_workload_identity_pool.github" \
  "projects/${PROJECT_ID}/locations/global/workloadIdentityPools/github-actions-pool"
tf_import "google_iam_workload_identity_pool_provider.github" \
  "projects/${PROJECT_ID}/locations/global/workloadIdentityPools/github-actions-pool/providers/github-actions-provider"

# ── Phase 5: Project-level IAM bindings ──────────────────────────────────────
echo ""
echo "Phase 5: Project-level IAM bindings"
tf_import "google_project_iam_member.extraction_runner_bq_job_user" \
  "${PROJECT_ID} roles/bigquery.jobUser serviceAccount:extraction-runner@${PROJECT_ID}.iam.gserviceaccount.com"
tf_import "google_project_iam_member.dbt_runner_bq_job_user" \
  "${PROJECT_ID} roles/bigquery.jobUser serviceAccount:dbt-runner@${PROJECT_ID}.iam.gserviceaccount.com"
tf_import "google_project_iam_member.ci_ar_writer" \
  "${PROJECT_ID} roles/artifactregistry.writer serviceAccount:github-actions-ci@${PROJECT_ID}.iam.gserviceaccount.com"
tf_import "google_project_iam_member.workflow_runner_invoker" \
  "${PROJECT_ID} roles/run.invoker serviceAccount:workflow-runner@${PROJECT_ID}.iam.gserviceaccount.com"
tf_import "google_project_iam_member.workflow_runner_viewer" \
  "${PROJECT_ID} roles/run.viewer serviceAccount:workflow-runner@${PROJECT_ID}.iam.gserviceaccount.com"
tf_import "google_project_iam_member.scheduler_runner_wf_invoker" \
  "${PROJECT_ID} roles/workflows.invoker serviceAccount:scheduler-runner@${PROJECT_ID}.iam.gserviceaccount.com"

# ── Phase 6: SA-level IAM bindings ──────────────────────────────────────────
echo ""
echo "Phase 6: SA-level IAM bindings"
tf_import "google_service_account_iam_member.extraction_runner_sa_user" \
  "projects/${PROJECT_ID}/serviceAccounts/extraction-runner@${PROJECT_ID}.iam.gserviceaccount.com roles/iam.serviceAccountUser serviceAccount:extraction-runner@${PROJECT_ID}.iam.gserviceaccount.com"
tf_import "google_service_account_iam_member.ci_wif_user" \
  "projects/${PROJECT_ID}/serviceAccounts/github-actions-ci@${PROJECT_ID}.iam.gserviceaccount.com roles/iam.workloadIdentityUser principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-actions-pool/attribute.repository/${GITHUB_REPO}"
tf_import "google_service_account_iam_member.ci_token_creator" \
  "projects/${PROJECT_ID}/serviceAccounts/github-actions-ci@${PROJECT_ID}.iam.gserviceaccount.com roles/iam.serviceAccountTokenCreator principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/github-actions-pool/attribute.repository/${GITHUB_REPO}"

# ── Phase 7: BigQuery datasets ──────────────────────────────────────────────
echo ""
echo "Phase 7: BigQuery datasets"
for ds in raw staging warehouses marts agent_registry; do
  tf_import "google_bigquery_dataset.datasets[\"${ds}\"]" \
    "projects/${PROJECT_ID}/datasets/${ds}"
done

# ── Phase 8: BigQuery dataset access ────────────────────────────────────────
echo ""
echo "Phase 8: BigQuery dataset access"
echo "  NOTE: google_bigquery_dataset_access imports can be tricky."
echo "  If imports fail, terraform plan will show these as 'add' operations,"
echo "  which is safe — BigQuery dataset access additions are idempotent."
tf_import "google_bigquery_dataset_access.extraction_raw_writer" \
  "projects/${PROJECT_ID}/datasets/raw userByEmail:extraction-runner@${PROJECT_ID}.iam.gserviceaccount.com WRITER" || true
tf_import "google_bigquery_dataset_access.dbt_raw_reader" \
  "projects/${PROJECT_ID}/datasets/raw userByEmail:dbt-runner@${PROJECT_ID}.iam.gserviceaccount.com READER" || true
tf_import "google_bigquery_dataset_access.dbt_staging_writer" \
  "projects/${PROJECT_ID}/datasets/staging userByEmail:dbt-runner@${PROJECT_ID}.iam.gserviceaccount.com WRITER" || true
tf_import "google_bigquery_dataset_access.dbt_warehouses_writer" \
  "projects/${PROJECT_ID}/datasets/warehouses userByEmail:dbt-runner@${PROJECT_ID}.iam.gserviceaccount.com WRITER" || true
tf_import "google_bigquery_dataset_access.dbt_marts_writer" \
  "projects/${PROJECT_ID}/datasets/marts userByEmail:dbt-runner@${PROJECT_ID}.iam.gserviceaccount.com WRITER" || true

# ── Phase 9–11: Cloud Run Jobs, Workflows, Schedulers ───────────────────────
# These are generated per-source from the sources map in terraform.tfvars.
# After you have added your sources and run terraform plan, import each
# existing resource using the patterns below (one block per source):
#
# SOURCE=my-source
# FREQ=daily
#
# Cloud Run Jobs (5 per source):
# for stage in extract dbt-stg-warehouse dbt-warehouse dbt-stg-marts dbt-mart; do
#   tf_import "google_cloud_run_v2_job.jobs[\"${SOURCE}-${stage}-${FREQ}\"]" \
#     "projects/${PROJECT_ID}/locations/${REGION}/jobs/${SOURCE}-${stage}-${FREQ}"
# done
#
# Cloud Workflow:
# tf_import "google_workflows_workflow.pipelines[\"${SOURCE}\"]" \
#   "projects/${PROJECT_ID}/locations/${REGION}/workflows/${SOURCE}-pipeline"
#
# Cloud Scheduler:
# tf_import "google_cloud_scheduler_job.pipelines[\"${SOURCE}\"]" \
#   "projects/${PROJECT_ID}/locations/${REGION}/jobs/${SOURCE}-pipeline-${FREQ}"
echo ""
echo "Phases 9–11: Cloud Run Jobs, Workflows, Schedulers"
echo "  → These are source-specific. See import.sh comments for the import pattern."

echo ""
echo "══════════════════════════════════════════════════════════════════"
echo "Import complete. Next steps:"
echo "  1. terraform plan    — review for drift (target: zero changes)"
echo "  2. Fix any diffs in .tf files until plan is clean"
echo "  3. terraform apply   — only if plan shows safe, non-destructive changes"
echo "══════════════════════════════════════════════════════════════════"
