---
name: ci-debugging
description: >
  CI failure diagnosis and fix guide for this repo. Auto-invoke when a GitHub
  Actions job fails (lint, docker-build, or deploy), when sqlfluff or ruff
  reports errors, when a Docker build fails, or when GCP authentication fails
  in CI. Do NOT load for general CI/CD questions unrelated to this repo.
---

# CI Debugging

CI runs two workflows:
- `ci.yml` — triggered on `pull_request` to `main`: `lint` then `docker-build`
- `deploy.yml` — triggered on `push` to `main`: build + push to Artifact Registry

**Hard rule: never use `--no-verify` or skip pre-commit hooks. Fix the root cause.**

---

## `lint` job failures

### ruff (Python)

Common violations and fixes:

| Error code | Meaning | Fix |
|---|---|---|
| `F401` | Unused import | Remove the import |
| `E501` | Line too long | Break the line or shorten variable names |
| `F841` | Local variable assigned but never used | Remove or use the variable |
| `E711` | Comparison to `None` using `==` | Use `is None` / `is not None` |

Run locally to see all errors before pushing:
```bash
ruff check 01_extraction/
```

Auto-fix safe violations:
```bash
ruff check --fix 01_extraction/
```

### sqlfluff (SQL)

Three rules are enforced (`--dialect bigquery`):

| Rule | Meaning | Fix |
|---|---|---|
| `LT01` | Trailing whitespace | Remove trailing spaces on each line |
| `RF04` | Keywords must be uppercase | `select` → `SELECT`, `from` → `FROM`, etc. |
| `LT05` | Line too long (>120 chars) | Break long `SELECT` lists or `JOIN` conditions across lines |

Run locally:
```bash
sqlfluff lint 02_dbt/models/ --dialect bigquery
```

Auto-fix:
```bash
sqlfluff fix 02_dbt/models/ --dialect bigquery
```

### Pre-commit: UTF-8 BOM failure

Error message: `fix utf-8 byte order marker...Failed`

Cause: File was saved with a BOM (common when editing on Windows).

Fix — strip the BOM:
```bash
# PowerShell
$content = Get-Content -Raw -Encoding utf8 path/to/file.sql
[System.IO.File]::WriteAllText("path/to/file.sql", $content, [System.Text.UTF8Encoding]::new($false))
```

Or re-save the file in your editor with UTF-8 (no BOM) encoding.

---

## `docker-build` job failures

### Bad `requirements.txt`

Symptoms: `pip install` step fails with `No matching distribution found` or version conflict.

Fix checklist:
- Verify the package name is correct (check PyPI)
- Pin to a version that exists: `google-cloud-bigquery==3.11.4` not `==99.0`
- Run `pip install -r requirements.txt` locally in a clean venv to reproduce

### Broken `Dockerfile`

Dockerfile template — verify all four elements are present:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY main.py .
CMD ["python", "main.py"]
```

Common mistakes:
- `COPY main.py` missing → container starts but immediately fails
- `WORKDIR` not set → files land in `/` and paths break
- `RUN pip install` before `COPY requirements.txt` → always cache-misses or fails

Test locally:
```bash
docker build 01_extraction/<source>/
```

---

## `deploy` job failures (post-merge on `main`)

These run after merge, so secrets are available. Failures here mean the code was valid but GCP configuration is wrong.

### GCP auth failure

Error: `Error: google-github-actions/auth failed...`

Check:
1. `WORKLOAD_IDENTITY_PROVIDER` secret is set in repo Settings → Secrets → Actions
2. `SERVICE_ACCOUNT` secret is set (must be the `github-actions-ci` SA email)
3. Get correct values: `terraform output workload_identity_provider` and `terraform output github_actions_sa_email`

### Artifact Registry push failure

Error: `denied: Permission denied` or `repository does not exist`

Check:
1. `GCP_REGION` variable matches the region where Artifact Registry was provisioned
2. `GCP_PROJECT_ID` variable is correct
3. The `extraction` repository exists: `gcloud artifacts repositories list --location=$GCP_REGION`
4. The `github-actions-ci` SA has `roles/artifactregistry.writer` — verify in `iam.tf`

---

## General debugging steps

1. Click the failing job in the GitHub Actions UI — read the exact error line, not just the job name
2. Reproduce locally before pushing a fix
3. Fix the root cause — do not suppress warnings or add `|| true` to skip failures
4. If pre-commit blocks a commit, fix the file and re-stage, then commit fresh (never `--no-verify`)
