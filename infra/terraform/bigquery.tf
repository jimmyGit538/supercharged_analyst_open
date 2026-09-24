# ── BigQuery datasets ────────────────────────────────────────────────────────

locals {
  # Pipeline datasets live in the same region as Cloud Run Jobs.
  # agent_registry was created in US multiregion — must match to avoid destroy/recreate.
  dataset_locations = {
    raw            = var.region
    stg_warehouses = var.region
    warehouses     = var.region
    stg_marts      = var.region
    marts          = var.region
    agent_registry = "US"

    # Legacy: predates the stg_warehouses/stg_marts split. Retained only as the
    # default connection dataset for the `cloudrun` dbt target (02_dbt/profiles.yml)
    # — every model overrides it via +schema, so nothing is materialised here.
    staging = var.region
  }
}

resource "google_bigquery_dataset" "datasets" {
  for_each   = local.dataset_locations
  dataset_id = each.key
  location   = each.value

  depends_on = [google_project_service.apis]
}

# ── Dataset-level access ─────────────────────────────────────────────────────
# Least-privilege, dataset-scoped grants. The runner SAs get no project-level
# BigQuery data roles — only jobUser (iam.tf) plus these bindings.
#
# google_bigquery_dataset_iam_member is additive: it adds one member to one
# role and leaves every other entry alone, so it coexists with anything
# infra/setup.sh granted in the legacy WRITER/READER format on an existing
# project. Never add an `access {}` block to google_bigquery_dataset.datasets
# above — mixing that authoritative form with these members is unsupported.

locals {
  dataset_access = {
    extraction_writes_raw = {
      dataset = "raw"
      role    = "roles/bigquery.dataEditor"
      member  = google_service_account.extraction_runner.email
    }
    dbt_reads_raw = {
      dataset = "raw"
      role    = "roles/bigquery.dataViewer"
      member  = google_service_account.dbt_runner.email
    }
    dbt_writes_stg_warehouses = {
      dataset = "stg_warehouses"
      role    = "roles/bigquery.dataEditor"
      member  = google_service_account.dbt_runner.email
    }
    dbt_writes_warehouses = {
      dataset = "warehouses"
      role    = "roles/bigquery.dataEditor"
      member  = google_service_account.dbt_runner.email
    }
    dbt_writes_stg_marts = {
      dataset = "stg_marts"
      role    = "roles/bigquery.dataEditor"
      member  = google_service_account.dbt_runner.email
    }
    dbt_writes_marts = {
      dataset = "marts"
      role    = "roles/bigquery.dataEditor"
      member  = google_service_account.dbt_runner.email
    }
  }
}

resource "google_bigquery_dataset_iam_member" "access" {
  for_each   = local.dataset_access
  dataset_id = google_bigquery_dataset.datasets[each.value.dataset].dataset_id
  role       = each.value.role
  member     = "serviceAccount:${each.value.member}"
}
