.PHONY: setup setup-local test dbt-debug dbt-run dbt-test tf-plan tf-apply

setup:       ## Full-stack setup (git, dbt, .env, tfvars, terraform init)
	bash scripts/setup.sh --full-stack

setup-local: ## Local dev only (git hooks + dbt)
	bash scripts/setup.sh --local-dev

test:        ## Unit test the extractors (no GCP access needed)
	pytest tests/

dbt-debug:   ## Verify BigQuery connection
	dbt debug --profiles-dir 02_dbt --project-dir 02_dbt

dbt-run:     ## Run all dbt models
	dbt run --profiles-dir 02_dbt --project-dir 02_dbt

dbt-test:    ## Run all dbt tests
	dbt test --profiles-dir 02_dbt --project-dir 02_dbt

tf-plan:     ## Terraform plan
	cd infra/terraform && terraform plan

tf-apply:    ## Terraform apply
	cd infra/terraform && terraform apply
