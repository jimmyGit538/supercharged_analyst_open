# ── Cloud Workflows ───────────────────────────────────────────────────────────
# One workflow per source pipeline. The YAML is hand-authored with polling
# and error handling — referenced via file(), not generated.
#
# Convention: infra/workflows/<source_key>_pipeline.yaml

resource "google_workflows_workflow" "pipelines" {
  for_each        = var.sources
  name            = "${each.key}-pipeline"
  region          = var.region
  service_account = google_service_account.workflow_runner.id
  source_contents = file("${path.module}/../workflows/${each.key}_pipeline.yaml")

  depends_on = [google_project_service.apis]
}
