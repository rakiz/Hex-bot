#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

docker build -t hex-bot:local .
echo "Image built: hex-bot:local"
