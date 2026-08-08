#!/usr/bin/env bash
# GCP project bootstrap script
# Run ONCE to configure the project environment.
#
# Before running:
#   1. Export your values:
#        export PROJECT_ID="my-project-123"
#        export REGION="us-central1"
#        export GITHUB_REPO="org/repo"
#   2. Authenticate: gcloud auth login && gcloud auth application-default login
#   3. Run: bash infra/setup.sh
#
# After running, the script prints the GitHub Actions secrets/variables you
# must add to the repository settings.

set -euo pipefail

PROJECT_ID="${PROJECT_ID:-YOUR_GCP_PROJECT_ID}"                  # e.g. my-project-123
REGION="${REGION:-YOUR_REGION}"                                   # e.g. us-central1
GITHUB_REPO="${GITHUB_REPO:-YOUR_GITHUB_ORG/YOUR_GITHUB_REPO}"   # e.g. acme/supercharged-analyst

# GitHub OIDC tokens always emit the repo name in its canonical case.
# Normalise to lowercase so WIF principal set bindings match the token claims.
GITHUB_REPO="${GITHUB_REPO,,}"

# Fail fast if placeholders were not replaced
if [[ "$PROJECT_ID" == YOUR_* || "$REGION" == YOUR_* || "$GITHUB_REPO" == YOUR_* ]]; then
  echo "ERROR: Set PROJECT_ID, REGION, and GITHUB_REPO before running." >&2
  echo "  export PROJECT_ID=my-project-123" >&2
  echo "  export REGION=us-central1" >&2
  echo "  export GITHUB_REPO=org/repo" >&2
  exit 1
fi

REPO_NAME="extraction"
WIF_POOL="github-actions-pool"
WIF_PROVIDER="github-actions-provider"
CI_SA_NAME="github-actions-ci"

echo "Configuring project: $PROJECT_ID"
gcloud config set project "$PROJECT_ID"

# ── Enable APIs ────────────────────────────────────────────────────────────────
gcloud services enable \
  run.googleapis.com \
  cloudscheduler.googleapis.com \
  workflows.googleapis.com \
  bigquery.googleapis.com \
  artifactregistry.googleapis.com \
  logging.googleapis.com \
  monitoring.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  sts.googleapis.com

# ── Artifact Registry ──────────────────────────────────────────────────────────
gcloud artifacts repositories create "$REPO_NAME" \
  --repository-format=docker \
  --location="$REGION" \
  --description="Extraction job container images" \
  || echo "Repository '${REPO_NAME}' already exists — skipping"

# ── Service accounts ───────────────────────────────────────────────────────────
# Extraction job runner — used by Cloud Run jobs at runtime
gcloud iam service-accounts create extraction-runner \
  --display-name="Extraction Job Runner" \
  || echo "Service account 'extraction-runner' already exists — skipping"

EXTRACTION_SA="extraction-runner@${PROJECT_ID}.iam.gserviceaccount.com"

# CI/CD service account — used by GitHub Actions via WIF (no key file)
gcloud iam service-accounts create "$CI_SA_NAME" \
  --display-name="GitHub Actions CI" \
  || echo "Service account '${CI_SA_NAME}' already exists — skipping"

CI_SA="${CI_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

# Wait for service accounts to propagate before binding IAM policies
echo "Waiting for service accounts to propagate..."
sleep 15

# Grant CI SA permission to push images to Artifact Registry
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${CI_SA}" \
  --role="roles/artifactregistry.writer"

# ── Workload Identity Federation ───────────────────────────────────────────────
# Allows GitHub Actions to authenticate as the CI SA without a key file.
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')

gcloud iam workload-identity-pools create "$WIF_POOL" \
  --project="$PROJECT_ID" \
  --location="global" \
  --display-name="GitHub Actions Pool" \
  || echo "WIF pool '${WIF_POOL}' already exists — skipping"

WIF_POOL_NAME="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${WIF_POOL}"

gcloud iam workload-identity-pools providers create-oidc "$WIF_PROVIDER" \
  --project="$PROJECT_ID" \
  --location="global" \
  --workload-identity-pool="$WIF_POOL" \
  --display-name="GitHub Actions Provider" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.actor=assertion.actor,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository=='${GITHUB_REPO}'" \
  || echo "WIF provider '${WIF_PROVIDER}' already exists — skipping"

# Allow any workflow in this repo to impersonate the CI SA.
# workloadIdentityUser: lets the WIF principal exchange tokens.
# serviceAccountTokenCreator: lets it generate SA access tokens (required by
# google-github-actions/auth when service_account param is used).
gcloud iam service-accounts add-iam-policy-binding "$CI_SA" \
  --project="$PROJECT_ID" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/${WIF_POOL_NAME}/attribute.repository/${GITHUB_REPO}"

gcloud iam service-accounts add-iam-policy-binding "$CI_SA" \
  --project="$PROJECT_ID" \
  --role="roles/iam.serviceAccountTokenCreator" \
  --member="principalSet://iam.googleapis.com/${WIF_POOL_NAME}/attribute.repository/${GITHUB_REPO}"

# ── BigQuery datasets ──────────────────────────────────────────────────────────
for dataset in raw stg_warehouses warehouses stg_marts marts staging agent_registry; do
  bq --project_id="$PROJECT_ID" mk \
    --dataset \
    --location="$REGION" \
    "${PROJECT_ID}:${dataset}" \
    || echo "Dataset '${dataset}' already exists — skipping"
done

# Grant extraction SA Data Editor on the raw dataset (dataset-level, least privilege)
# bq add-iam-policy-binding requires allowlisting, so we use bq show/update with a temp file
TMPFILE=$(mktemp /tmp/bq_raw_acl.XXXXXX.json)
bq show --format=json "${PROJECT_ID}:raw" > "$TMPFILE"
python3 - "$TMPFILE" "${EXTRACTION_SA}" <<'PYEOF'
import sys, json

path, sa = sys.argv[1], sys.argv[2]
with open(path) as f:
    data = json.load(f)

access = data.get("access", [])
if any(e.get("userByEmail") == sa for e in access):
    print(f"{sa} already has access to raw dataset — skipping")
else:
    access.append({"role": "WRITER", "userByEmail": sa})
    with open(path, "w") as f:
        json.dump({"access": access}, f)
    print(f"Granted WRITER access on raw dataset to {sa}")
PYEOF
bq update --source="$TMPFILE" "${PROJECT_ID}:raw"
rm -f "$TMPFILE"

# Grant extraction SA BigQuery Job User at project level (needed to run queries)
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${EXTRACTION_SA}" \
  --role="roles/bigquery.jobUser"

# Allow Cloud Run to use the extraction SA
gcloud iam service-accounts add-iam-policy-binding "$EXTRACTION_SA" \
  --project="$PROJECT_ID" \
  --member="serviceAccount:${EXTRACTION_SA}" \
  --role="roles/iam.serviceAccountUser"

# ── dbt runner service account ─────────────────────────────────────────────────
# Used by the dbt-indices Cloud Run Job at runtime.
gcloud iam service-accounts create dbt-runner \
  --display-name="dbt Runner" \
  || echo "Service account 'dbt-runner' already exists — skipping"

DBT_SA="dbt-runner@${PROJECT_ID}.iam.gserviceaccount.com"

# dbt needs to create/replace relations in every layer dataset it materialises into
for dataset in stg_warehouses warehouses stg_marts marts; do
  TMPFILE=$(mktemp /tmp/bq_${dataset}_acl.XXXXXX.json)
  bq show --format=json "${PROJECT_ID}:${dataset}" > "$TMPFILE"
  python3 - "$TMPFILE" "${DBT_SA}" <<'PYEOF'
import sys, json
path, sa = sys.argv[1], sys.argv[2]
with open(path) as f:
    data = json.load(f)
access = data.get("access", [])
if any(e.get("userByEmail") == sa for e in access):
    print(f"{sa} already has access — skipping")
else:
    access.append({"role": "WRITER", "userByEmail": sa})
    with open(path, "w") as f:
        json.dump({"access": access}, f)
    print(f"Granted WRITER access on {path} to {sa}")
PYEOF
  bq update --source="$TMPFILE" "${PROJECT_ID}:${dataset}"
  rm -f "$TMPFILE"
done

# dbt also needs read access to the raw dataset (via staging views)
TMPFILE=$(mktemp /tmp/bq_raw_dbt_acl.XXXXXX.json)
bq show --format=json "${PROJECT_ID}:raw" > "$TMPFILE"
python3 - "$TMPFILE" "${DBT_SA}" <<'PYEOF'
import sys, json
path, sa = sys.argv[1], sys.argv[2]
with open(path) as f:
    data = json.load(f)
access = data.get("access", [])
if any(e.get("userByEmail") == sa for e in access):
    print(f"{sa} already has read access — skipping")
else:
    access.append({"role": "READER", "userByEmail": sa})
    with open(path, "w") as f:
        json.dump({"access": access}, f)
    print(f"Granted READER access on raw dataset to {sa}")
PYEOF
bq update --source="$TMPFILE" "${PROJECT_ID}:raw"
rm -f "$TMPFILE"

# dbt runner needs BigQuery Job User to run queries
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${DBT_SA}" \
  --role="roles/bigquery.jobUser"

# ── Output GitHub configuration ────────────────────────────────────────────────
WIF_PROVIDER_FULL="projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${WIF_POOL}/providers/${WIF_PROVIDER}"

echo ""
echo "══════════════════════════════════════════════════════════════════"
echo "Bootstrap complete. Add these to GitHub → Settings → Secrets and variables:"
echo ""
echo "  Secrets (Settings → Secrets → Actions):"
echo "    WORKLOAD_IDENTITY_PROVIDER = ${WIF_PROVIDER_FULL}"
echo "    SERVICE_ACCOUNT            = ${CI_SA}"
echo ""
echo "  Variables (Settings → Variables → Actions):"
echo "    GCP_PROJECT_ID = ${PROJECT_ID}"
echo "    GCP_REGION     = ${REGION}"
echo "══════════════════════════════════════════════════════════════════"
echo ""
echo "Next: run 'bash infra/agent_registry/deploy.sh' to provision registry tables."
