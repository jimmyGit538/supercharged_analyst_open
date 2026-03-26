# ── Cloud Run Jobs ────────────────────────────────────────────────────────────
# One job per entry in local.all_jobs (extraction + dbt, auto-generated).

resource "google_cloud_run_v2_job" "jobs" {
  for_each = local.all_jobs
  name     = each.key
  location = var.region

  template {
    template {
      service_account = each.value.sa_email
      timeout         = "600s"
      max_retries     = 1

      containers {
        image = each.value.image
        args  = length(each.value.args) > 0 ? each.value.args : null

        dynamic "env" {
          for_each = each.value.env_vars
          content {
            name  = env.key
            value = env.value
          }
        }

        dynamic "env" {
          for_each = each.value.secrets
          content {
            name = env.key
            value_source {
              secret_key_ref {
                secret  = env.key
                version = env.value
              }
            }
          }
        }
      }
    }
  }

  depends_on = [google_project_service.apis]
}

# ── Cloud Scheduler ──────────────────────────────────────────────────────────
# One scheduler job per source pipeline, triggering the Cloud Workflow.

resource "google_cloud_scheduler_job" "pipelines" {
  for_each  = var.sources
  name      = "${each.key}-pipeline-${each.value.frequency}"
  region    = var.region
  schedule  = each.value.schedule
  time_zone = each.value.schedule_tz

  http_target {
    http_method = "POST"
    uri         = "https://workflowexecutions.googleapis.com/v1/${google_workflows_workflow.pipelines[each.key].id}/executions"
    body = base64encode(jsonencode({
      argument = jsonencode({ region = var.region })
    }))
    oauth_token {
      service_account_email = google_service_account.scheduler_runner.email
    }
  }

  depends_on = [google_project_service.apis]
}
