#!/usr/bin/env bash
# Sync app code to origin (perso), then merge into the kanopy branch and push
# that as 10gen/main (which contains app code + internal MongoDB/Kanopy files).
#
# Usage:
#   ./sync-10gen.sh               — push to both remotes + update 10gen/main
#   ./sync-10gen.sh --app-only    — push app code to origin only
#   ./sync-10gen.sh --kanopy-only — push kanopy branch to 10gen only (no origin push)
set -e

cd "$(dirname "$0")"

APP_ONLY=false
KANOPY_ONLY=false
if [[ "${1:-}" == "--app-only" ]]; then
  APP_ONLY=true
elif [[ "${1:-}" == "--kanopy-only" ]]; then
  KANOPY_ONLY=true
fi

if $KANOPY_ONLY; then
  CURRENT=$(git branch --show-current)
  if [[ "$CURRENT" != "kanopy" ]]; then
    echo "✗ Must be on 'kanopy' to use --kanopy-only (currently on '$CURRENT')."
    exit 1
  fi
  if ! git diff --quiet || ! git diff --cached --quiet; then
    echo "✗ Uncommitted changes detected. Commit or stash them first."
    exit 1
  fi
  echo "→ Pushing kanopy to 10gen/main..."
  git push 10gen kanopy:main
  echo ""
  echo "✓ Done."
  echo "  10gen (interne): Kanopy config pushed"
  exit 0
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

if $APP_ONLY; then
  echo "✓ App code pushed to origin."
  exit 0
fi

echo "→ Merging main into kanopy branch..."
git checkout kanopy
git merge main --no-edit
echo "→ Pushing kanopy to 10gen/main..."
git push 10gen kanopy:main
git checkout main

echo ""
echo "✓ Done."
echo "  origin (perso)  : app code"
echo "  10gen  (interne): app code + Kanopy config"
