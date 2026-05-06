locals {
  # ── Extraction jobs: one per source ──────────────────────────────────────────
  extraction_jobs = {
    for name, src in var.sources :
    "${name}-extract-${src.frequency}" => {
      source   = name
      image    = "${var.region}-docker.pkg.dev/${var.project_id}/extraction/${src.extraction_image}:latest"
      sa_email = google_service_account.extraction_runner.email
      env_vars = src.env_vars
      secrets  = src.secrets
      args     = []
      timeout  = src.timeout
    }
  }

  # ── dbt stages: fixed pattern per source ─────────────────────────────────────
  # Each stage maps to a dbt command that matches create_jobs.sh exactly.
  dbt_stages = {
    "dbt-stg-warehouse" = "dbt run --profiles-dir /app --project-dir /app --target cloudrun --select 1_staging_warehouses"
    "dbt-warehouse"     = "dbt seed --profiles-dir /app --project-dir /app --target cloudrun && dbt run --profiles-dir /app --project-dir /app --target cloudrun --select 2_warehouses"
    "dbt-stg-marts"     = "dbt run --profiles-dir /app --project-dir /app --target cloudrun --select 3_staging_marts"
    "dbt-mart"          = "dbt run --profiles-dir /app --project-dir /app --target cloudrun --select 4_marts"
  }

  # ── dbt jobs: cross-product of sources x stages ──────────────────────────────
  dbt_jobs = merge([
    for name, src in var.sources : {
      for stage, cmd in local.dbt_stages :
      "${name}-${stage}-${src.frequency}" => {
        source   = name
        image    = "${var.region}-docker.pkg.dev/${var.project_id}/extraction/dbt-runner:latest"
        sa_email = google_service_account.dbt_runner.email
        env_vars = { BQ_PROJECT = var.project_id }
        secrets  = {}
        args     = ["sh", "-c", cmd]
        timeout  = "600s"
      }
    }
  ]...)

  # ── All Cloud Run Jobs combined ──────────────────────────────────────────────
  all_jobs = merge(local.extraction_jobs, local.dbt_jobs)
}
