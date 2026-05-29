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

echo ""
echo "Setup complete. See CONTRIBUTING.md for the recommended remote configuration."
