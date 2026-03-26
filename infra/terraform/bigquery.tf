# ── BigQuery datasets ────────────────────────────────────────────────────────

locals {
  # Pipeline datasets live in the same region as Cloud Run Jobs.
  # agent_registry was created in US multiregion — must match to avoid destroy/recreate.
  dataset_locations = {
    raw              = var.region
    staging          = var.region
    warehouses       = var.region
    marts            = var.region
    agent_registry   = "US"
  }
}

resource "google_bigquery_dataset" "datasets" {
  for_each   = local.dataset_locations
  dataset_id = each.key
  location   = each.value

  depends_on = [google_project_service.apis]
}

# ── Dataset-level access ─────────────────────────────────────────────────────
# Dataset access entries are managed by infra/setup.sh (legacy WRITER/READER
# format). The google_bigquery_dataset_access resource does not support import,
# so these remain outside Terraform management.
#
# Current access (configured by setup.sh):
#   - extraction-runner: WRITER on raw
#   - dbt-runner:        READER on raw
#   - dbt-runner:        WRITER on staging, warehouses, marts
