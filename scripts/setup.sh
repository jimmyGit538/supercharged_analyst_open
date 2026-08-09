#!/usr/bin/env bash
# One-time setup for contributors. Run after cloning.
# Usage: bash scripts/setup.sh [--local-dev | --full-stack | --configure-github]
#
#   --local-dev        git hooks + dbt only (no GCP credentials required)
#   --full-stack       the above + .env + terraform.tfvars + terraform init
#   --configure-github read terraform outputs and set the GitHub Actions secrets
#                      and variables. Run AFTER `terraform apply`.

set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"
TF_DIR="$REPO_ROOT/infra/terraform"

usage() {
  echo "Usage: bash scripts/setup.sh [--local-dev | --full-stack | --configure-github]" >&2
}

# ── Mode selection ─────────────────────────────────────────────────────────────

MODE=""
for arg in "$@"; do
  case "$arg" in
    --local-dev)        MODE="local"  ;;
    --full-stack)       MODE="full"   ;;
    --configure-github) MODE="github" ;;
    *)
      echo "Unknown flag: $arg" >&2
      usage
      exit 1
      ;;
  esac
done

if [ -z "$MODE" ]; then
  echo "Setup mode:"
  echo "  1) local-dev        — git hooks + dbt only (no GCP credentials required)"
  echo "  2) full-stack       — git hooks + dbt + .env + terraform.tfvars + terraform init"
  echo "  3) configure-github — set GitHub Actions secrets/variables from terraform outputs"
  printf "Enter 1, 2 or 3 [1]: "
  read -r CHOICE
  case "${CHOICE:-1}" in
    1) MODE="local"  ;;
    2) MODE="full"   ;;
    3) MODE="github" ;;
    *)
      usage
      exit 1
      ;;
  esac
fi

# ── GitHub Actions configuration ───────────────────────────────────────────────
# Reads the Terraform outputs and writes the two secrets and two variables the
# Deploy workflow needs. This is the step that otherwise means copy-pasting four
# values into the GitHub web UI.
#
# Secrets must be encrypted against the repository public key, which is why this
# goes through `gh` rather than a plain REST call.

derive_repo() {
  if [ -n "${GITHUB_REPO:-}" ]; then
    printf '%s' "$GITHUB_REPO"
    return 0
  fi
  local url
  url=$(git -C "$REPO_ROOT" remote get-url origin 2>/dev/null) || return 1
  # git@github.com:owner/repo.git | https://github.com/owner/repo.git -> owner/repo
  printf '%s' "$url" | sed -E 's#^(https://|git@)([^/:]+)[/:]##; s#\.git$##'
}

configure_github() {
  command -v gh        >/dev/null 2>&1 || { echo "ERROR: gh CLI not found. Install: https://cli.github.com" >&2; exit 1; }
  command -v terraform >/dev/null 2>&1 || { echo "ERROR: terraform not found." >&2; exit 1; }

  gh auth status >/dev/null 2>&1 || {
    echo "ERROR: gh is not authenticated. Run: gh auth login" >&2
    exit 1
  }

  local repo
  repo=$(derive_repo) || true
  if [ -z "${repo:-}" ]; then
    echo "ERROR: could not determine the GitHub repo. Set GITHUB_REPO=owner/repo and re-run." >&2
    exit 1
  fi

  local outputs
  if ! outputs=$(terraform -chdir="$TF_DIR" output -json 2>/dev/null) || [ -z "$outputs" ] || [ "$outputs" = "{}" ]; then
    echo "ERROR: no Terraform outputs found." >&2
    echo "  Run this first:  cd infra/terraform && terraform apply" >&2
    exit 1
  fi

  # Emits: NAME<TAB>VALUE<TAB>kind, one per line. Exits non-zero if any output is
  # missing, which means the apply predates the gcp_project_id/gcp_region outputs.
  local pairs
  pairs=$(printf '%s' "$outputs" | python3 -c '
import json, sys

# Windows Python defaults to CRLF line endings, which would leave a trailing
# \r on the last field and silently misclassify a secret as a variable.
sys.stdout.reconfigure(newline="\n")

data = json.load(sys.stdin)

MAPPING = [
    ("WORKLOAD_IDENTITY_PROVIDER", "wif_provider",       "secret"),
    ("SERVICE_ACCOUNT",            "ci_service_account", "secret"),
    ("GCP_PROJECT_ID",             "gcp_project_id",     "variable"),
    ("GCP_REGION",                 "gcp_region",         "variable"),
]

missing = [out for _, out, _ in MAPPING if out not in data]
if missing:
    sys.exit(
        "missing terraform output(s): " + ", ".join(missing)
        + "\n  Re-run `terraform apply` — outputs.tf may be newer than your state."
    )

for name, out, kind in MAPPING:
    value = data[out]["value"]
    print(f"{name}\t{value}\t{kind}")
')

  if [ -z "$pairs" ]; then
    echo "ERROR: could not read the required values from Terraform." >&2
    exit 1
  fi

  echo ""
  echo "Configuring GitHub Actions for $repo ..."

  local name value kind
  while IFS=$'\t' read -r name value kind; do
    [ -n "$name" ] || continue
    kind=${kind%$'\r'}   # belt and braces against CRLF from a Windows python3
    if [ "$kind" != "secret" ] && [ "$kind" != "variable" ]; then
      echo "ERROR: unrecognised kind '$kind' for $name — refusing to write." >&2
      exit 1
    fi
    # Values are never echoed — only the name and kind.
    if [ "$kind" = "secret" ]; then
      gh secret set "$name" -R "$repo" --body "$value" >/dev/null
    else
      gh variable set "$name" -R "$repo" --body "$value" >/dev/null
    fi
    STATUS_PASS+=("$name set ($kind)")
    echo "  [x] $name ($kind)"
  done <<< "$pairs"

  local expected=4 actual
  actual=$(printf '%s\n' "$pairs" | grep -c . || true)
  if [ "$actual" -lt "$expected" ]; then
    STATUS_TODO+=("GCP_PROJECT_ID / GCP_REGION not found in terraform.tfvars — set them manually")
    echo "  [!] only $actual of $expected values set — check infra/terraform/terraform.tfvars" >&2
  fi
}

# ── Status tracking ────────────────────────────────────────────────────────────

STATUS_PASS=()
STATUS_TODO=()
STATUS_WARN=()

# configure-github is a standalone post-apply step — it needs neither the dbt
# install nor the git hooks, so run it and stop here.
if [ "$MODE" = "github" ]; then
  configure_github
  echo ""
  echo "Done. Verify with:  gh secret list && gh variable list"
  echo "Then push images:   gh workflow run deploy.yml   (or merge to main)"
  if [ ${#STATUS_TODO[@]} -gt 0 ]; then
    echo ""
    echo " TODO:"
    for item in "${STATUS_TODO[@]}"; do
      echo "  [ ] $item"
    done
  fi
  exit 0
fi

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
  echo "  [ ] bash scripts/setup.sh --configure-github"
  echo "        sets WORKLOAD_IDENTITY_PROVIDER, SERVICE_ACCOUNT (secrets) and"
  echo "        GCP_PROJECT_ID, GCP_REGION (variables) from the terraform outputs"
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
