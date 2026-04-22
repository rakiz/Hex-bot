#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

git config core.hooksPath .githooks
chmod +x .githooks/pre-push

echo "Git hooks installed."
