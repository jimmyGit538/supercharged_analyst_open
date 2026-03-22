#!/usr/bin/env bash
# Deploy agent registry schema to BigQuery and seed all definitions.
#
# Prerequisites:
#   - BQ_PROJECT and BQ_DATASET set in .env or environment
#   - infra/agent_registry/requirements.txt installed
#   - Authenticated: gcloud auth application-default login
#
# Usage:
#   bash infra/agent_registry/deploy.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

# Load .env if present
if [[ -f "${ROOT_DIR}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source "${ROOT_DIR}/.env"
  set +a
fi

: "${BQ_PROJECT:?BQ_PROJECT must be set in environment or .env}"
: "${BQ_DATASET:?BQ_DATASET must be set in environment or .env}"

echo "Deploying agent registry to ${BQ_PROJECT}.${BQ_DATASET} ..."

# ── Schema ─────────────────────────────────────────────────────────────────────
# Substitute {PROJECT} and {DATASET} placeholders, then run via bq CLI
sed \
  "s/{PROJECT}/${BQ_PROJECT}/g; s/{DATASET}/${BQ_DATASET}/g" \
  "${SCRIPT_DIR}/schema.sql" \
| bq query \
    --project_id="${BQ_PROJECT}" \
    --nouse_legacy_sql

echo "Schema deployed."

# ── Seed definitions ────────────────────────────────────────────────────────────
# manage.py uses `from agent_registry.snapshot import ...` so must run from infra/
echo "Seeding agents and skills ..."
cd "${ROOT_DIR}/infra"

python -m agent_registry.manage upsert \
  --type agent \
  --name data-extractor \
  --file "${ROOT_DIR}/.claude/agents/data-extractor.md" \
  --notes "initial seed"

python -m agent_registry.manage upsert \
  --type skill \
  --name python-data-extraction \
  --file "${ROOT_DIR}/.claude/skills/python-data-extraction/SKILL.md" \
  --notes "initial seed"

python -m agent_registry.manage upsert \
  --type skill \
  --name data-pipeline-patterns \
  --file "${ROOT_DIR}/.claude/skills/data-pipeline-patterns/SKILL.md" \
  --notes "initial seed"

echo ""
echo "Agent registry ready. Verify with:"
echo "  python -m infra.agent_registry.manage list --type agent --name data-extractor"
echo "  python -m infra.agent_registry.manage list --type skill --name python-data-extraction"
