---
name: pr-workflow
description: >
  PR workflow standards for this repo. Auto-invoke when opening a pull request,
  pushing a branch, writing a commit message, or responding to PR review feedback.
  Do NOT load for general git questions unrelated to contributing to this repo.
---

# PR Workflow

## Branch naming

Pattern: `<verb>-<short-description>` (kebab-case, no issue numbers required)

```
add-stripe-pipeline
fix-fred-incremental-watermark
improve-dbt-modeler-agent
refactor-terraform-sources-map
```

## Commit messages

One subject line (imperative mood, ≤72 chars). Body is optional — use it only when the why is non-obvious.

Always end with the co-author line:

```
Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

Pass multi-line messages via heredoc to avoid shell quoting issues:

```bash
git commit -m "$(cat <<'EOF'
Add Stripe pipeline extraction job

Incremental extraction using created timestamp watermark stored in
BigQuery. Handles Stripe's cursor-based pagination.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
EOF
)"
```

## One logical change per PR

Keep diffs reviewable. Split when:
- A new data source + a CI fix are both in scope → two PRs
- A new skill + an agent improvement are both in scope → two PRs

Bundle when:
- Extraction job + its dbt models + its Terraform entry are all for the same source → one PR
- A skill rewrite + its frontmatter description update → one PR

## Draft vs ready-for-review

Open as **draft** when:
- CI hasn't run yet and you expect failures to fix
- The extraction job works but dbt models are incomplete

Open as **ready-for-review** only when:
- `lint` and `docker-build` CI jobs are green
- The change matches what the PR description says

## PR body format

```markdown
## Summary

- <bullet: what changed and why>
- <bullet: any non-obvious decisions>

## Test plan

- [ ] CI lint and docker-build pass
- [ ] <source-specific check, e.g. "manual Cloud Run Job execution returns rows in raw dataset">
- [ ] <dbt check if applicable, e.g. "dbt run --select <source> completes without errors">

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

Keep the Summary to 2–4 bullets. The diff is the detail — the PR body explains the why.

## Responding to review feedback

- Fix requested changes in a **new commit** (do not amend published commits)
- Re-request review after pushing the fix
- If a reviewer asks a question that changes the scope, comment with your reasoning before pushing

## Merge

- Squash merge is fine for single-commit PRs; merge commit for multi-commit PRs
- Delete the branch after merge
- Never push directly to `main`
