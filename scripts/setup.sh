#!/usr/bin/env bash
# One-time setup for contributors. Run after cloning.
# Registers the merge=ours driver and installs the pre-push hook.

set -e

REPO_ROOT="$(git rev-parse --show-toplevel)"

# Register the merge=ours driver (prevents private paths from being overwritten
# when merging upstream framework updates into a private fork)
git config merge.ours.driver true
echo "merge=ours driver registered"

# Install pre-push hook (blocks accidental pushes of private code to the public repo)
HOOK_SRC="$REPO_ROOT/.githooks/pre-push"
HOOK_DST="$REPO_ROOT/.git/hooks/pre-push"
cp "$HOOK_SRC" "$HOOK_DST"
chmod +x "$HOOK_DST"
echo "pre-push hook installed"

# Install dbt and its BigQuery adapter
echo "Installing dbt dependencies..."
pip install -r 02_dbt/requirements.txt

# Install dbt packages (dbt_utils etc.) defined in packages.yml
echo "Installing dbt packages..."
dbt deps --profiles-dir 02_dbt --project-dir 02_dbt

echo ""
echo "Setup complete. See CONTRIBUTING.md for the recommended remote configuration."
echo "Next: copy .env.example to .env, fill in BQ_PROJECT, then run 'gcloud auth application-default login'."
echo "Verify your dbt connection with: dbt debug --profiles-dir 02_dbt --project-dir 02_dbt"
