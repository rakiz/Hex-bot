#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

# Start ngrok in background and capture its PID
ngrok http 8080 --log=stdout > /tmp/hex-ngrok.log 2>&1 &
NGROK_PID=$!

# Wait for ngrok to be up and print the public URL
echo "Starting ngrok..."
for i in $(seq 1 10); do
  URL=$(curl -s http://localhost:4040/api/tunnels 2>/dev/null | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['tunnels'][0]['public_url'])" 2>/dev/null || true)
  if [ -n "$URL" ]; then
    echo "ngrok tunnel: $URL"
    echo "Slack events URL: $URL/slack/events"
    break
  fi
  sleep 1
done

cleanup() {
  echo ""
  echo "Shutting down..."
  kill $NGROK_PID 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo ""
echo "Starting Flask..."
.venv/bin/python -m hex_bot.app
