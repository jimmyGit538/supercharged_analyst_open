output "wif_provider" {
  description = "Full Workload Identity Provider resource name (for GitHub Actions secrets)"
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "ci_service_account" {
  description = "GitHub Actions CI service account email"
  value       = google_service_account.github_actions_ci.email
}

output "extractor_service_account" {
  description = "Extraction runner service account email"
  value       = google_service_account.extraction_runner.email
}

output "dbt_service_account" {
  description = "dbt runner service account email"
  value       = google_service_account.dbt_runner.email
}

output "cloud_run_job_names" {
  description = "All Cloud Run Job names"
  value       = { for k, v in google_cloud_run_v2_job.jobs : k => v.name }
}

output "workflow_ids" {
  description = "Workflow resource IDs (per source)"
  value       = { for k, w in google_workflows_workflow.pipelines : k => w.id }
}

output "scheduler_names" {
  description = "Cloud Scheduler job names (per source)"
  value       = { for k, v in google_cloud_scheduler_job.pipelines : k => v.name }
}
