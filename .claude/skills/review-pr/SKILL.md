---
name: review-pr
description: >
  Local PR review workflow for the repo maintainer. Fetches a contributor PR
  by number, runs a structured Claude-powered analysis (security, scope,
  conventions, value), and prints a verdict to the terminal.

  Invoke when the user types /review-pr <number> or asks to review an
  incoming pull request before merging.

  Do NOT invoke for reviewing your own branch changes — use /security-review
  or /code-review for that instead.
---

# PR Review — Maintainer Workflow

## What this skill does

You are running as the maintainer's local assistant. When invoked with a PR number, you will:

1. Fetch the PR metadata and diff using the `gh` CLI
2. Load the `pr-reviewer` agent definition to get the full review checklist
3. Analyse the PR diff against that checklist
4. Print a structured verdict: security findings, scope check, convention check, value assessment

This runs entirely locally. No comments are posted to GitHub unless the maintainer explicitly asks.

---

## Step 1 — Parse the PR number

Extract the PR number from the skill arguments. If no number was provided, ask:

> "Which PR number would you like me to review?"

---

## Step 2 — Fetch PR data with gh CLI

Run these commands to gather all context:

```bash
# PR metadata: title, author, description, labels, files changed
gh pr view <number> --repo <owner>/<repo> --json title,author,body,files,labels,url

# Full diff
gh pr diff <number> --repo <owner>/<repo>
```

To get the repo name, run:
```bash
gh repo view --json nameWithOwner -q .nameWithOwner
```

If `gh` is not authenticated or the repo can't be determined, tell the maintainer:
> "Run `gh auth login` first, then retry."

---

## Step 3 — Run the review

With the PR title, author, body, files list, and full diff in hand, apply the complete `pr-reviewer` agent checklist:

- Security screening (secrets, injection, typosquats, obfuscation, GH Actions changes)
- Scope check (accepted contribution types, no hardcoded real values, one logical change)
- Convention check (skill frontmatter, extractor structure, dbt naming, infra patterns)
- Value assessment (genuine improvement, clean implementation, not a duplicate)

Work through the diff file by file. Be thorough on security — read every `requirements.txt`, every new Python file, every workflow YAML change.

---

## Step 4 — Print the review

Output the structured review in the format defined in the `pr-reviewer` agent:

```
## PR Review — "<title>"
Author: <author> | Files changed: <n> | Verdict: <approve | request-changes | reject>

### Security
...

### Scope
...

### Conventions
...

### Value
...

### Recommendation
...
```

End with the PR URL so the maintainer can jump straight to it:
```
PR: <url>
```

---

## After the review

Ask the maintainer:
> "Would you like me to post this review as a GitHub comment, or is this just for your reference?"

If they want to post it: use `gh pr comment <number> --body "<review text>"` to add the formatted review as a PR comment. Do not approve, request changes, or close the PR via the API unless explicitly asked.
