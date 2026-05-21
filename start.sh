#!/usr/bin/env bash
# Single-command launcher for the full demo.
#
# Compose (background) runs the backend stack: Flask, LiveKit, Postgres, MinIO.
# The broadcaster runs on the HOST because it needs direct camera, microphone,
# and X11 display access — three things that are individually fiddly in Docker
# and collectively fragile to combine. See
# docs/decisions/003-python-broadcaster-not-phone.md.

set -euo pipefail

cd "$(dirname "$0")"

if [[ ! -f .env ]]; then
  echo "No .env found. Copy .env.example to .env and set LIVEKIT_API_SECRET first."
  exit 1
fi

# Host-level libs the broadcaster needs (sounddevice / OpenCV). These can't go
# in requirements.txt — they're apt packages, not PyPI ones. See
# broadcaster/BROADCASTER.md.
if command -v ldconfig >/dev/null 2>&1; then
  # Cache ldconfig output in a variable to avoid an `ldconfig | grep -q`
  # pipeline: under `set -o pipefail`, grep -q exits early on first match,
  # closes the pipe, and ldconfig dies with SIGPIPE → the whole pipeline is
  # reported as failed, incorrectly flagging the lib as missing.
  ldconfig_out="$(ldconfig -p)"
  missing=()
  grep -q "libportaudio\.so" <<<"$ldconfig_out" || missing+=("libportaudio2")
  grep -q "libGL\.so"        <<<"$ldconfig_out" || missing+=("libgl1")
  grep -q "libglib-2\.0\.so" <<<"$ldconfig_out" || missing+=("libglib2.0-0")
  if (( ${#missing[@]} > 0 )); then
    echo "Missing host libraries: ${missing[*]}"
    echo "Install with: sudo apt install -y ${missing[*]}"
    exit 1
  fi
fi

# ------------------------------------------------------------------
# 1. Backend stack via docker compose
# ------------------------------------------------------------------
echo "Starting backend stack (postgres, livekit, backend, minio)…"
docker compose up -d --build

# Wait for Flask to start accepting connections so the broadcaster's first
# POST /api/v1/streams doesn't race the boot.
echo -n "Waiting for backend…"
for _ in $(seq 1 60); do
  if curl -fsS http://localhost:5001/api/v1/streams >/dev/null 2>&1; then
    echo " ready."
    break
  fi
  echo -n "."
  sleep 1
done

# ------------------------------------------------------------------
# 2. Broadcaster on the host
# ------------------------------------------------------------------
# Use the broadcaster's own .env if present so camera index etc. can differ
# from the backend's. Fall back to the root .env vars otherwise.
if [[ -f broadcaster/.env ]]; then
  set -a
  # shellcheck disable=SC1091
  source broadcaster/.env
  set +a
fi

echo "Starting broadcaster (camera + mic + LiveKit publisher)…"
exec python -m broadcaster "$@"
