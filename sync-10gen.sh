#!/usr/bin/env bash
# Sync app code to both remotes, then update the 10gen deployment branch.
#
# Usage:
#   ./sync-10gen.sh           — push app code + update 10gen with kanopy branch
#   ./sync-10gen.sh --app-only — push app code to both remotes, skip kanopy rebase
set -e

cd "$(dirname "$0")"

APP_ONLY=false
if [[ "${1:-}" == "--app-only" ]]; then
  APP_ONLY=true
fi

# Must be on main to run this script
CURRENT=$(git branch --show-current)
if [[ "$CURRENT" != "main" ]]; then
  echo "✗ Must be on 'main' to sync (currently on '$CURRENT')."
  exit 1
fi

# Abort if there are uncommitted changes
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "✗ Uncommitted changes detected. Commit or stash them first."
  exit 1
fi

echo "→ Pushing app code to origin (perso)..."
git push origin main

echo "→ Pushing app code to 10gen..."
git push 10gen main

if $APP_ONLY; then
  echo "✓ App code synced to both remotes."
  exit 0
fi

echo "→ Rebasing kanopy branch on main..."
git checkout kanopy
git rebase main
echo "→ Pushing kanopy branch to 10gen/main..."
git push 10gen kanopy:main
git checkout main

echo ""
echo "✓ Done. Both remotes are up to date."
echo "  origin  (perso) : app code"
echo "  10gen   (interne): app code + Kanopy config"
