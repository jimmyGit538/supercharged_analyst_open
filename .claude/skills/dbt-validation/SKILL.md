---
name: dbt-validation
description: >
  Validate dbt code changes locally before pushing. Auto-invoke after editing,
  adding, moving, or renaming anything under 02_dbt/ — model SQL, _models.yml
  docs and tests, _sources.yml, seeds, macros, or dbt_project.yml — and when a
  dbt model or test fails locally, or when confirming a dbt refactor did not
  drop models, tests, or ref() edges. Do NOT load for validating a deployed
  pipeline in GCP (use pipeline-validation), for CI lint failures already
  reported by GitHub Actions (use ci-debugging), or for choosing a model's
  loading strategy (use data-pipeline-patterns).
metadata:
  tier: layer
  domain: modeling
---

# dbt Validation

Validates a **local code change** to `02_dbt/`. Three tiers, cheapest first. Run
them in order and stop at the first failure — a parse error makes every later
tier meaningless.

| Tier | Cost | Catches |
|---|---|---|
| 1 — Static | Free, no warehouse | Lint violations, bad Jinja, broken `ref()`, orphaned YAML |
| 2 — Dry build | ~0 bytes billed | Invalid SQL, column/type errors, missing upstream relations |
| 3 — Real build | Billed | Data quality failures, empty results, logic bugs |

**Scope boundary:** this skill stops at `--target dev`, which writes to the
`dbt_dev_*` sandbox datasets. Anything involving Cloud Run Jobs, Cloud Workflows,
or the `prod` target belongs to `pipeline-validation`.

---

## Step 0 — Environment

dbt runs from the repo root against the non-standard `profiles.yml` location:

```bash
source .env                 # sets BQ_PROJECT and DBT_PROFILES_DIR=02_dbt
dbt debug --project-dir 02_dbt
```

Without `.env` sourced, pass both flags explicitly on every command:

```bash
dbt debug --profiles-dir 02_dbt --project-dir 02_dbt
```

Every command below is written in the sourced-`.env` form. Confirm the toolchain
before trusting a failure — a version skew between `dbt-core` and `dbt-bigquery`
produces errors that look like model bugs:

```bash
dbt --version
```

If `packages.yml` or `dbt_project.yml` changed, refresh dependencies first:

```bash
dbt deps --project-dir 02_dbt
```

---

## Step 1 — Scope the change

Validate only what changed and what depends on it. A full-project build is the
wrong default: it is slow, it bills for unrelated models, and it buries the one
failure you caused in unrelated noise.

Derive the changed models from git:

```bash
git diff --name-only main...HEAD -- '02_dbt/**'
```

Turn each changed `.sql` path into a selector using the model name (the filename
without `.sql`) plus `+` for downstream:

```bash
dbt ls --select stg_open_meteo__daily_weather+ --output name --project-dir 02_dbt
```

Read the output before building. If it lists far more models than you expect,
the change is wider than intended — say so rather than building blind.

**Selector cheatsheet**

| Selector | Selects |
|---|---|
| `my_model` | That model alone |
| `my_model+` | It and everything downstream |
| `+my_model` | It and everything upstream |
| `1+my_model+` | One layer up, it, everything down |
| `4_marts` | Every mart model (matches the layer path) |
| `tag:open-meteo` | Every model of one source (the tag is the `terraform.tfvars` key) |
| `4_marts,tag:open-meteo` | One source's marts — exactly what its Cloud Run Job builds |
| `source:raw+` | Everything built off the `raw` source |

Model directories are the four layers under `02_dbt/models/`, so `--select
<layer>` works as a path selector. If you later split a layer into per-source
subdirectories, the same path selection applies one level deeper.

### state:modified

`state:modified` needs a baseline manifest, and `02_dbt/target/` is gitignored,
so no baseline exists by default. Create one from `main` **before** editing:

```bash
mkdir -p /tmp/dbt-baseline
git stash                                   # or: git worktree add for main
dbt parse --project-dir 02_dbt && cp 02_dbt/target/manifest.json /tmp/dbt-baseline/
git stash pop
```

Then:

```bash
dbt build --select state:modified+ --state /tmp/dbt-baseline --project-dir 02_dbt
```

A stale baseline silently selects the wrong models, so if you cannot vouch for
when the baseline was written, use explicit selectors from git diff instead. Do
not hand-wave this — a `state:modified` run that selects nothing looks identical
to a clean pass.

---

## Step 2 — Tier 1: static checks

### sqlfluff

Same command CI runs, so a pass here means the `lint` job passes:

```bash
sqlfluff lint 02_dbt/models/ --dialect bigquery
```

Scope it to the changed files while iterating:

```bash
sqlfluff lint 02_dbt/models/1_staging_warehouses/ --dialect bigquery
```

`.pre-commit-config.yaml` and CI both pin sqlfluff to 3.4.0, so a local run with
that version matches CI; if yours differs, match the pin. For violation-by-violation fixes (LT01, RF04, LT05, AL01,
ST06), load the `ci-debugging` skill rather than duplicating its tables here.

### Parse and compile

`dbt parse` resolves the DAG without touching BigQuery — it is the fastest way
to catch a broken `ref()`, a bad `source()`, or a Jinja syntax error:

```bash
dbt parse --project-dir 02_dbt
```

`dbt compile` additionally renders every model's SQL to `02_dbt/target/compiled/`.
Read the compiled output when a macro, `ref()`, or seed reference is not
resolving to what you expect:

```bash
dbt compile --select <selector> --project-dir 02_dbt
cat 02_dbt/target/compiled/supercharged_analyst/models/<layer>/<model>.sql
```

### Catch YAML that no longer matches a model

This is the failure mode that matters most after moving or renaming models:
docs and tests silently detach and nothing errors by default.

```bash
dbt parse --warn-error --project-dir 02_dbt
```

`--warn-error` promotes warnings to failures, so an `_models.yml` entry pointing
at a model that no longer exists at that path becomes a hard error instead of a
line of log output you skim past.

---

## Step 3 — Tier 2: dry build

Build the real relations with zero rows. This executes each model's SQL against
BigQuery with a `LIMIT 0`-style wrapper, so it validates column names, types,
and joins while scanning essentially nothing:

```bash
dbt build --select <selector> --empty --target dev --project-dir 02_dbt
```

This is the highest-value step in the whole skill: it catches the large majority
of broken-model errors at effectively no cost. Run it before any billed build.

Tests run against empty relations here, so a passing `--empty` build says
nothing about data quality — only that the SQL is structurally valid.

**When seeds exist, exclude them.** This template ships no seeds yet (see the
commented-out `seeds:` block in `dbt_project.yml`), but once you add one,
`--empty` is incompatible with seeds on dbt-bigquery: the seed loader issues a
`GET` for a table `--empty` never created and fails with `404 ... Not found:
Table ...dbt_dev_warehouses.<seed>`. Load them once normally, then dry-build
everything else:

```bash
dbt seed --target dev --project-dir 02_dbt
dbt build --select <selector> --empty --target dev \
  --exclude "resource_type:seed" --project-dir 02_dbt
```

A seed loaded this way is real data, not an empty relation, which is what lets
the `relationships` tests on seeded dimensions resolve at all.

### `--empty` leaves the sandbox empty, and Tier 3 will read it

`--empty` is not a dry run in the sense of "nothing persists". It really creates
every selected relation in `dbt_dev_*`, with each `ref()` and `source()`
rendered as `(select * from ... where false limit 0)`:

- **Views stay empty for good.** The stored view definition contains that
  wrapper, so the view returns 0 rows until it is rebuilt without `--empty` —
  in this session or any later one.
- **Incremental tables stay empty for good.** Their filter is built on
  `max(date)` from `{{ this }}`, including trailing-window forms such as
  `date_sub(max(existing.date), interval 90 day)`. On an empty table `max()` is
  NULL, the filter is false, and every later incremental run merges 0 rows.
  Only `--full-refresh` repopulates them.

The danger is the next step. A Tier 3 build that selects only the changed
models reads whatever sits upstream in `dbt_dev_*`. If that is a view left
empty by any earlier `--empty` run, every changed model builds from nothing,
and every test passes, because a test that looks for bad rows finds none in an
empty table. The only sign is `MERGE (0.0 rows, 0 processed)` or
`CREATE VIEW (0 processed)` in the log.

This is not hypothetical. In a deployment of this template, validating a change
to a warehouse returns model once passed every test, about 90 of them, on a
table with 0 rows. An earlier session had left the staging view upstream of it
as `where false limit 0`. Step 4 is set up to prevent this. Do not shorten its
selector.

---

## Step 4 — Tier 3: real build

Select the changed models **with everything upstream of them**, not just what
the Tier 2 selector covered:

```bash
dbt build --select +<changed>+ --target dev --project-dir 02_dbt
```

The leading `+` rebuilds every upstream view from `raw` for real. That overwrites
any `where false limit 0` definition left by Tier 2 or by an earlier session, so
the changed models read real data. Upstream staging models are views and cost
almost nothing to recreate, and the warehouse tables upstream are bounded by the
1 GB `dev` cap. For several changed models, list each one:
`--select +model_a+ +model_b+`.

`dbt build` interleaves `run`, `test`, and `seed` in DAG order, so a model whose
tests fail blocks its children instead of propagating bad data downstream.
Prefer it over a bare `dbt run` followed by `dbt test`.

**Incremental models created by `--empty` need `--full-refresh`.** The leading
`+` cannot fix them: an incremental run on an empty table merges 0 rows (see
Step 3). If the log shows `MERGE (0.0 rows, 0 processed)` for a model that should
have data, it needs `--full-refresh`. Ask the user before running it, per
Constraints. Scope it to the sandbox and to that model and its children:
`dbt build --full-refresh --select <model>+ --target dev --project-dir 02_dbt`.

**When a build stops on test failures that already exist,** dbt skips everything
downstream, and excluding failing tests one by one rarely ends: one upstream
data bug usually fails a similar test in every layer. Build the models, then
test them all, so every failure shows up in one pass:

```bash
dbt run  --select +<changed>+ --target dev --project-dir 02_dbt
dbt test --select +<changed>+ --target dev --project-dir 02_dbt
```

Then run each failing test's query against production. A failure with a similar
count in prod existed before your change: report it, don't fix it in this PR. A
failure only in dev is yours.

### Prove the build read real data

A green Tier 3 build does not show that any rows were built (see Step 3). After it
runs, check both kinds of empty relation.

Views still compiled with the `--empty` wrapper, in both staging datasets:

```bash
for ds in dbt_dev_stg_warehouses dbt_dev_stg_marts; do
  bq query --use_legacy_sql=false --format=pretty "
    select table_schema, table_name
    from \`$BQ_PROJECT.$ds.INFORMATION_SCHEMA.VIEWS\`
    where regexp_contains(view_definition, r'where false\s+limit 0')"
done
```

Empty tables:

```bash
for ds in dbt_dev_warehouses dbt_dev_marts; do
  bq query --use_legacy_sql=false --format=pretty "
    select dataset_id, table_id, row_count
    from \`$BQ_PROJECT.$ds.__TABLES__\`
    where row_count = 0"
done
```

Query each dataset separately. Region-level `INFORMATION_SCHEMA` needs
project-wide `bigquery.tables.list`, which a developer account may not have;
the dataset-level views do not. Neither query reads table data, so neither bills
meaningfully.

Results that belong to other pipelines are left over from earlier sessions.
They don't matter unless a model in your `+<changed>+` selection reads them.
Any changed model, or anything upstream of one, that appears in either result
means Tier 3 did not validate it: rebuild it, then rerun the check.

### What `--target dev` isolates, and how to confirm it

`dev` writes to the `dbt_dev_stg_warehouses`, `dbt_dev_warehouses`,
`dbt_dev_stg_marts`, and `dbt_dev_marts` sandbox datasets, so it cannot touch the
production datasets Looker Studio reads.

That isolation comes from `02_dbt/macros/generate_schema_name.sql` prefixing
`target.schema` onto each model's `+schema` for any target outside
`('prod', 'cloudrun')` — **not** from the `dataset:` field in `profiles.yml`,
which a bare `custom_schema_name` ignores entirely.

This is worth verifying rather than assuming, because the macro governs every
model in every environment and a regression in it writes to production silently:

```bash
dbt --quiet parse --target dev --project-dir 02_dbt
python -c "import json; m=json.load(open('02_dbt/target/manifest.json')); \
  print(sorted({n['schema'] for n in m['nodes'].values() \
  if n['resource_type'] in ('model', 'seed')}))"
```

Expected on `dev`:

```
['dbt_dev_marts', 'dbt_dev_stg_marts', 'dbt_dev_stg_warehouses', 'dbt_dev_warehouses']
```

If any entry reads bare `stg_warehouses`, `warehouses`, `stg_marts`, or `marts`,
stop — the macro has regressed to returning `custom_schema_name` verbatim, and a
build will write into production.

Filter to models and seeds as above. An unfiltered list also contains
`dbt_test__audit`, which is dbt's own store-failures schema and never carries the
prefix — treating its presence as a failure is a false alarm.

Run the same check with `--target cloudrun` after touching the macro: it must
return the bare `['marts', 'stg_marts', 'stg_warehouses', 'warehouses']`, or the
deployed pipeline will start writing to sandbox datasets. Never validate against
`--target prod`.

### Cost controls

The `dev` target sets `maximum_bytes_billed: 1000000000` (1 GB), so a runaway
local build is killed rather than billed. Deployed targets are deliberately
uncapped, so that ceiling is no protection when validating through Cloud Run.

A model that trips the 1 GB ceiling is telling you something — check its cost
before raising the limit:

```bash
dbt compile --select <model> --project-dir 02_dbt
# then dry-run the compiled SQL
bq query --use_legacy_sql=false --dry_run \
  < 02_dbt/target/compiled/supercharged_analyst/models/<layer>/<model>.sql
```

If a seed changed, seeds must load before dependent models. `dbt build` handles
the ordering; a standalone `dbt run` does not.

---

## Step 5 — Refactor integrity check

Run this when models moved, were renamed, or when a layer was reorganised —
cases where the build passes and coverage has quietly regressed.

Compare resource counts against `main`:

`dbt ls` writes its log preamble to stdout alongside the results, which
silently inflates any count or diff. `--quiet` is mandatory here, not cosmetic:

```bash
dbt --quiet ls --resource-type model --output name --project-dir 02_dbt | wc -l
dbt --quiet ls --resource-type test  --output name --project-dir 02_dbt | wc -l
```

Check the same two numbers on `main` (via `git worktree add` or `git stash`).
Both must match unless the change intentionally added or removed resources.

- **Model count dropped** → a file was lost or is outside `model-paths`.
- **Test count dropped** → an `_models.yml` entry detached from its model. This
  is the most common regression in a directory reorganisation, and it is
  invisible in a green build.

Then diff the full name lists to confirm the *same* resources exist, not merely
the same count:

```bash
dbt --quiet ls --resource-type model --output name --project-dir 02_dbt \
  | sort > /tmp/after.txt
diff /tmp/before.txt /tmp/after.txt
```

Get the baseline from a worktree rather than a stash, so both lists come from the
same dbt install without disturbing your working tree:

```bash
git worktree add /tmp/main-baseline main
dbt deps       --project-dir /tmp/main-baseline/02_dbt --profiles-dir /tmp/main-baseline/02_dbt
dbt --quiet ls --project-dir /tmp/main-baseline/02_dbt --profiles-dir /tmp/main-baseline/02_dbt \
  --resource-type model --output name | sort > /tmp/before.txt
git worktree remove /tmp/main-baseline
```

Cross-check the counts against dbt's own `Found N models, N data tests` summary
line. If they disagree, log lines leaked into your list.

Directory moves do not change model names, so for a pure move this diff must be
empty. Any line in it is a bug.

---

## Failure triage

| Symptom | Cause | Fix |
|---|---|---|
| `Compilation Error: model 'x' depends on a node named 'y' which was not found` | Broken `ref()` — renamed or deleted upstream model | Fix the `ref()`, or restore the model. Check for a stale `_models.yml` entry too |
| `Found two models with the same name` | Same filename in two directories | dbt names are global, not path-scoped. Rename one to `<source>__<entity>` |
| `Relation ... was not found` on `--empty` | Upstream relation never built in `dbt_dev_*` | Widen the selector upstream: `+<model>` |
| `Column not found` | Staging model does not match actual raw schema | Inspect the raw table; align the staging columns |
| `Unable to do partial parsing` | Profile, vars, or target changed | Informational, not an error. Ignore, or `rm -rf 02_dbt/target/` for a clean parse |
| Test fails only on the real build | Genuine data quality issue | Inspect the data before touching the test. Weaken severity only with a documented reason |
| Model builds, mart returns 0 rows | A `WHERE` or `JOIN` filters everything | Run the compiled SQL directly in BigQuery and bisect the predicates |
| Real build is green but logs `MERGE (0.0 rows, 0 processed)` / changed tables have 0 rows | An upstream `dbt_dev_*` view still holds an earlier `--empty` build's `where false limit 0`, or an incremental table was first created by `--empty` | Rebuild with `--select +<changed>+`; `--full-refresh` the incremental models (with approval). Then run the checks in Step 4 → *Prove the build read real data* |
| A known failing test blocks the build, and excluding it surfaces the same failure one layer down | One upstream data bug fails a similar test in every layer | `dbt run` then `dbt test` the selection, and compare each failure's count with prod (Step 4) |
| Lint passes locally, fails in CI | Version skew | CI and `.pre-commit-config.yaml` both pin `sqlfluff==3.4.0`. Match the pin locally, and bump both together |

---

## Definition of done

Before opening a PR touching `02_dbt/`:

- [ ] `sqlfluff lint 02_dbt/models/ --dialect bigquery` clean
- [ ] `dbt parse --warn-error` clean
- [ ] Every schema in the manifest starts with `dbt_dev_` (Step 4)
- [ ] `dbt build --select <changed>+ --empty --target dev` passes
- [ ] `dbt build --select +<changed>+ --target dev` passes with tests, with
      upstream included so no relation left empty by `--empty` is read
- [ ] No changed model or upstream relation appears in the empty-view or
      empty-table checks (Step 4 → *Prove the build read real data*)
- [ ] Every new or changed column has a description and at least one test
- [ ] Model and test counts reconcile against `main` (Step 5), for a refactor
- [ ] Row counts on affected marts are non-zero and plausible
- [ ] Every test failure is either fixed or shown to exist in prod already
      with a similar count, and reported as such

Report what actually ran. A tier that was skipped — because dbt could not
authenticate, or the build was too expensive — must be stated as skipped, not
folded into a general claim that validation passed.

---

## Constraints

- Never validate against `--target prod`.
- Never run `dbt run-operation`, `--full-refresh` on a warehouse or mart table,
  or any command that drops a relation, without explicit user approval.
- `dbt build` on `--target dev` is safe and non-destructive; do not ask before
  running it on changed models.
- Do not weaken or delete a failing test to make a build pass. Fix the data or
  the model, or surface the tradeoff to the user.
- `02_dbt/target/` and `02_dbt/dbt_packages/` are gitignored — never commit them.
