# ── Service accounts ──────────────────────────────────────────────────────────

resource "google_service_account" "extraction_runner" {
  account_id   = "extraction-runner"
  display_name = "Extraction Job Runner"
}

resource "google_service_account" "dbt_runner" {
  account_id   = "dbt-runner"
  display_name = "dbt Runner"
}

resource "google_service_account" "github_actions_ci" {
  account_id   = "github-actions-ci"
  display_name = "GitHub Actions CI"
}

resource "google_service_account" "workflow_runner" {
  account_id   = "workflow-runner"
  display_name = "Cloud Workflows Runner"
}

resource "google_service_account" "scheduler_runner" {
  account_id   = "scheduler-runner"
  display_name = "Cloud Scheduler Runner"
}

# ── Project-level IAM bindings (non-authoritative) ──────────────────────────

resource "google_project_iam_member" "extraction_runner_bq_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.extraction_runner.email}"
}

resource "google_project_iam_member" "dbt_runner_bq_job_user" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.dbt_runner.email}"
}

resource "google_project_iam_member" "ci_ar_writer" {
  project = var.project_id
  role    = "roles/artifactregistry.writer"
  member  = "serviceAccount:${google_service_account.github_actions_ci.email}"
}

resource "google_project_iam_member" "workflow_runner_invoker" {
  project = var.project_id
  role    = "roles/run.invoker"
  member  = "serviceAccount:${google_service_account.workflow_runner.email}"
}

resource "google_project_iam_member" "workflow_runner_viewer" {
  project = var.project_id
  role    = "roles/run.viewer"
  member  = "serviceAccount:${google_service_account.workflow_runner.email}"
}

resource "google_project_iam_member" "scheduler_runner_wf_invoker" {
  project = var.project_id
  role    = "roles/workflows.invoker"
  member  = "serviceAccount:${google_service_account.scheduler_runner.email}"
}

# ── Secret Manager access ─────────────────────────────────────────────────────

# Grant extraction-runner accessor on every secret referenced across all sources
resource "google_secret_manager_secret_iam_member" "extraction_runner_secret_accessor" {
  for_each  = toset(flatten([for s in var.sources : keys(s.secrets)]))
  secret_id = each.value
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.extraction_runner.email}"

  depends_on = [google_project_service.apis]
}

# ── SA-level IAM bindings ────────────────────────────────────────────────────

# Allow Cloud Run to use the extraction SA
resource "google_service_account_iam_member" "extraction_runner_sa_user" {
  service_account_id = google_service_account.extraction_runner.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.extraction_runner.email}"
}

# ── Workload Identity Federation ─────────────────────────────────────────────

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github-actions-pool"
  display_name              = "GitHub Actions Pool"

  depends_on = [google_project_service.apis]
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github-actions-provider"
  display_name                       = "GitHub Actions Provider"

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.actor"      = "assertion.actor"
    "attribute.repository" = "assertion.repository"
  }

  attribute_condition = "assertion.repository=='${var.github_repo}'"
}

# Allow GitHub Actions workflows to impersonate the CI SA
resource "google_service_account_iam_member" "ci_wif_user" {
  service_account_id = google_service_account.github_actions_ci.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repo}"
}

resource "google_service_account_iam_member" "ci_token_creator" {
  service_account_id = google_service_account.github_actions_ci.name
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repo}"
}
