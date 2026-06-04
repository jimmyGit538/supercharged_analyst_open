#!/usr/bin/env bash
# One-time setup for contributors. Run after cloning.
# Usage: bash scripts/setup.sh [--local-dev | --full-stack]

set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"

# ── Mode selection ─────────────────────────────────────────────────────────────

MODE=""
for arg in "$@"; do
  case "$arg" in
    --local-dev)  MODE="local" ;;
    --full-stack) MODE="full"  ;;
    *)
      echo "Unknown flag: $arg" >&2
      echo "Usage: bash scripts/setup.sh [--local-dev | --full-stack]" >&2
      exit 1
      ;;
  esac
done

if [ -z "$MODE" ]; then
  echo "Setup mode:"
  echo "  1) local-dev  — git hooks + dbt only (no GCP credentials required)"
  echo "  2) full-stack — git hooks + dbt + .env + terraform.tfvars + terraform init"
  printf "Enter 1 or 2 [1]: "
  read -r CHOICE
  case "${CHOICE:-1}" in
    1) MODE="local" ;;
    2) MODE="full"  ;;
    *)
      echo "Invalid choice. Run with --local-dev or --full-stack." >&2
      exit 1
      ;;
  esac
fi

# ── Status tracking ────────────────────────────────────────────────────────────

STATUS_PASS=()
STATUS_TODO=()
STATUS_WARN=()

# ── Prerequisite checks ────────────────────────────────────────────────────────

check_cmd() {
  local cmd="$1" label="$2" required="${3:-optional}"
  if ! command -v "$cmd" &>/dev/null; then
    if [ "$required" = "required" ]; then
      echo "ERROR: $label not found. Install it and re-run." >&2
      exit 1
    else
      STATUS_WARN+=("$label not found — needed for GCP/infrastructure steps")
    fi
  fi
}

check_cmd python3  "python3"  required
check_cmd pip      "pip"      required

if [ "$MODE" = "full" ]; then
  check_cmd gcloud    "gcloud CLI"  required
  check_cmd terraform "terraform"   required
else
  check_cmd gcloud    "gcloud CLI"  optional
  check_cmd terraform "terraform"   optional
fi

check_cmd docker "docker" optional

# ── Git setup ─────────────────────────────────────────────────────────────────

# Register the merge=ours driver (prevents private paths from being overwritten
# when merging upstream framework updates into a private fork)
git config merge.ours.driver true
STATUS_PASS+=("merge=ours driver registered")

# Install pre-push hook (blocks accidental pushes of private code to the public repo)
HOOK_SRC="$REPO_ROOT/.githooks/pre-push"
HOOK_DST="$REPO_ROOT/.git/hooks/pre-push"
cp "$HOOK_SRC" "$HOOK_DST"
chmod +x "$HOOK_DST"
STATUS_PASS+=("pre-push hook installed")

# ── .env bootstrap ─────────────────────────────────────────────────────────────

ENV_FILE="$REPO_ROOT/.env"
if [ ! -f "$ENV_FILE" ]; then
  cp "$REPO_ROOT/.env.example" "$ENV_FILE"
  STATUS_PASS+=(".env created from .env.example")
  STATUS_TODO+=("Edit .env — fill in BQ_PROJECT, DBT_SERVICE_ACCOUNT, and any API keys")
else
  STATUS_PASS+=(".env already exists — skipped copy")
  if grep -q "YOUR_GCP_PROJECT_ID" "$ENV_FILE" 2>/dev/null; then
    STATUS_TODO+=(".env still has placeholder values — fill in BQ_PROJECT and DBT_SERVICE_ACCOUNT")
  fi
fi

# ── dbt setup ─────────────────────────────────────────────────────────────────

echo ""
echo "Installing dbt dependencies..."
pip install -r "$REPO_ROOT/02_dbt/requirements.txt"

echo ""
echo "Installing dbt packages..."
dbt deps --profiles-dir "$REPO_ROOT/02_dbt" --project-dir "$REPO_ROOT/02_dbt"
STATUS_PASS+=("dbt-bigquery and packages installed")

# ── Terraform setup (full-stack only) ─────────────────────────────────────────

if [ "$MODE" = "full" ]; then
  TFVARS="$REPO_ROOT/infra/terraform/terraform.tfvars"

  if [ ! -f "$TFVARS" ]; then
    cp "$REPO_ROOT/infra/terraform/terraform.tfvars.example" "$TFVARS"
    STATUS_PASS+=("terraform.tfvars created from example")
    STATUS_TODO+=("Edit infra/terraform/terraform.tfvars — set project_id, region, github_repo")
  else
    STATUS_PASS+=("terraform.tfvars already exists — skipped copy")
  fi

  echo ""
  echo "Running terraform init..."
  pushd "$REPO_ROOT/infra/terraform" > /dev/null
  if terraform init -input=false; then
    STATUS_PASS+=("terraform init complete")
  else
    STATUS_WARN+=("terraform init failed — run manually: cd infra/terraform && terraform init")
  fi
  popd > /dev/null
fi

# ── Summary ───────────────────────────────────────────────────────────────────

BAR="══════════════════════════════════════════════════════"

echo ""
echo "$BAR"
echo " Setup Summary"
echo "$BAR"

echo ""
echo " DONE:"
for item in "${STATUS_PASS[@]}"; do
  echo "  [x] $item"
done

echo ""
echo " TODO (requires your credentials):"
for item in "${STATUS_TODO[@]}"; do
  echo "  [ ] $item"
done

if [ "$MODE" = "full" ]; then
  echo "  [ ] gcloud auth login && gcloud auth application-default login"
  echo "  [ ] cd infra/terraform && terraform plan && terraform apply"
  echo "  [ ] Add to GitHub → Settings → Secrets → Actions:"
  echo "        WORKLOAD_IDENTITY_PROVIDER  (run: terraform output wif_provider)"
  echo "        SERVICE_ACCOUNT             (run: terraform output ci_service_account)"
  echo "  [ ] Add to GitHub → Settings → Variables → Actions:"
  echo "        GCP_PROJECT_ID  GCP_REGION"
else
  echo "  [ ] gcloud auth application-default login"
fi
echo "  [ ] dbt debug --profiles-dir 02_dbt --project-dir 02_dbt"

if [ ${#STATUS_WARN[@]} -gt 0 ]; then
  echo ""
  echo " WARNINGS:"
  for item in "${STATUS_WARN[@]}"; do
    echo "  [!] $item"
  done
fi

echo ""
echo "$BAR"
