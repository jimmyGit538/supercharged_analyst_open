# Validate that secrets referenced by extraction jobs actually exist.
# These are data sources only — the actual secret values are created manually
# via gcloud or the GCP console. terraform plan will fail early if a
# referenced secret is missing.

data "google_secret_manager_secret" "extraction_secrets" {
  for_each  = toset(flatten([for s in var.sources : keys(s.secrets)]))
  secret_id = each.value

  depends_on = [google_project_service.apis]
}
