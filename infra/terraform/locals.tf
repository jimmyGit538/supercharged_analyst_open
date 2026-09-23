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
  # Each stage builds one model layer. The selector intersects the layer with
  # `tag:<source key>`, so a source's pipeline builds only its own models —
  # every model carries its source key in `config.tags` in its layer's
  # _schema.yml. `dbt build` runs models and their tests together, so a failing
  # test stops the workflow before bad data reaches the next layer.
  dbt_stages = {
    "dbt-stg-warehouse" = "1_staging_warehouses"
    "dbt-warehouse"     = "2_warehouses"
    "dbt-stg-marts"     = "3_staging_marts"
    "dbt-mart"          = "4_marts"
  }

  # ── dbt jobs: cross-product of sources x stages ──────────────────────────────
  dbt_jobs = merge([
    for name, src in var.sources : {
      for stage, layer in local.dbt_stages :
      "${name}-${stage}-${src.frequency}" => {
        source   = name
        image    = "${var.region}-docker.pkg.dev/${var.project_id}/extraction/dbt-runner:latest"
        sa_email = google_service_account.dbt_runner.email
        env_vars = { BQ_PROJECT = var.project_id }
        secrets  = {}
        args = [
          "dbt", "build",
          "--profiles-dir", "/app", "--project-dir", "/app",
          "--target", "cloudrun",
          "--select", "${layer},tag:${name}",
        ]
        timeout = "600s"
      }
    }
  ]...)

  # ── All Cloud Run Jobs combined ──────────────────────────────────────────────
  all_jobs = merge(local.extraction_jobs, local.dbt_jobs)
}
