# ── Cloud Workflows ───────────────────────────────────────────────────────────
# One workflow per source, rendered from templates/pipeline_workflow.yaml by
# substituting {source} and {frequency}. Plain replace() rather than
# templatefile(): the Workflows YAML is full of `${...}` expressions that
# templatefile() would try to evaluate.
#
# A source may set `workflow_file` (path relative to this directory) to supply
# its own hand-written YAML instead — the escape hatch for a pipeline whose
# shape differs from the standard five-job sequence.

locals {
  pipeline_template = file("${path.module}/templates/pipeline_workflow.yaml")

  workflow_contents = {
    for name, src in var.sources :
    name => src.workflow_file != null
    ? file("${path.module}/${src.workflow_file}")
    : replace(replace(local.pipeline_template, "{source}", name), "{frequency}", src.frequency)
  }
}

resource "google_workflows_workflow" "pipelines" {
  for_each        = var.sources
  name            = "${each.key}-pipeline"
  region          = var.region
  service_account = google_service_account.workflow_runner.id
  source_contents = local.workflow_contents[each.key]

  depends_on = [google_project_service.apis]
}
