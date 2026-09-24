# ── Pipeline failure alerting ─────────────────────────────────────────────────
# One alert policy for every source pipeline: fires when any Cloud Workflow
# managed here finishes an execution with status FAILED, and emails
# var.alert_email. Both resources are created only when alert_email is set,
# so a fork that has not configured an address gets no alerting and no
# notification channel — nothing to clean up, nothing to fail on.
#
# Every failure in the pipeline surfaces here: a Cloud Run Job that exits
# non-zero (extractor crash, dbt build error, failing dbt test) makes the
# workflow's check_* step raise, which marks the execution FAILED. What this
# does NOT catch is a workflow that never starts — e.g. Cloud Scheduler
# receiving a 403 — because no execution exists to fail.

locals {
  alerting_enabled = var.alert_email != ""

  # Scope the policy to the workflows Terraform manages, so unrelated workflows
  # in the same project do not page this address.
  alert_workflow_ids = join(", ", [for k in keys(var.sources) : "\"${k}-pipeline\""])
}

resource "google_monitoring_notification_channel" "pipeline_alerts_email" {
  count        = local.alerting_enabled ? 1 : 0
  display_name = "Data pipeline alerts"
  type         = "email"
  labels = {
    email_address = var.alert_email
  }

  depends_on = [google_project_service.apis]
}

resource "google_monitoring_alert_policy" "pipeline_failed" {
  count        = local.alerting_enabled ? 1 : 0
  display_name = "Data pipeline workflow failed"
  combiner     = "OR"

  conditions {
    display_name = "A pipeline workflow execution finished with status FAILED"

    condition_threshold {
      # finished_execution_count is a DELTA metric: one point per finished
      # execution, labelled with its status. Summing FAILED points per
      # workflow over the alignment window and alerting on > 0 fires once per
      # failed run, and stays quiet when there are no executions at all.
      filter = <<-EOT
        resource.type = "workflows.googleapis.com/Workflow"
        AND metric.type = "workflows.googleapis.com/finished_execution_count"
        AND metric.labels.status = "FAILED"
        AND resource.labels.workflow_id = one_of(${local.alert_workflow_ids})
      EOT

      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"

      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_SUM"
        cross_series_reducer = "REDUCE_SUM"
        group_by_fields      = ["resource.labels.workflow_id"]
      }

      trigger {
        count = 1
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.pipeline_alerts_email[0].id]

  alert_strategy {
    # Close the incident once the workflow has gone 30 minutes without a new
    # failure, so the next day's failure opens a fresh incident and re-notifies.
    auto_close = "1800s"
  }

  documentation {
    mime_type = "text/markdown"
    content   = <<-EOT
      A data pipeline Cloud Workflow finished with status FAILED. The workflow
      name is in the incident's `workflow_id` label; the failing step is one of
      its five Cloud Run Jobs (extract, then the four dbt stages).

      Find the failed job execution and its logs:

      ```
      gcloud workflows executions list <workflow_id> --location=<region> --limit=1
      gcloud run jobs executions list --job=<workflow_id minus "-pipeline">-<stage>-<frequency> --region=<region> --limit=1
      gcloud logging read 'resource.type="cloud_run_job" AND severity>=ERROR' --limit=50 --freshness=1d
      ```

      A dbt stage that fails with `FAIL` lines in its log is a data test
      failure, not a build error: inspect the data before touching the test.
    EOT
  }

  depends_on = [google_project_service.apis]
}
