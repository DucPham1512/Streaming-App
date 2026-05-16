#!/usr/bin/env bash
# Single-command launcher for the full backend stack.
# See docs/decisions/003-python-broadcaster-not-phone.md for why this exists.

set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
  echo "No .env found. Copy .env.example to .env and set LIVEKIT_API_SECRET first."
  exit 1
fi

# Until Commit 6b activates the broadcaster service, gestures still run via
# `python gesture_demo/demo.py --camera 2` on the host.
exec docker compose up --build "$@"
