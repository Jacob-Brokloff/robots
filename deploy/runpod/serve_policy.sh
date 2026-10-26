#!/usr/bin/env bash
# Serve the checkpoint to the Pi over the tailnet (CP14). Foreground; Ctrl+C stops it.
#   POLICY_CHECKPOINT=Jacob-Brokloff/pi05_xlerobot_<task> bash /workspace/robots/deploy/runpod/serve_policy.sh [--check]
# Binds 127.0.0.1:8765: tailscaled (userspace) forwards tailnet connections to local listeners, so the Pi
# dials ws://strands-pod:8765 (or the pod's tailnet IP). One client at a time, no TLS.
set -euo pipefail
WS="${WS:-/workspace}"
source "$WS/strands.env"
[ -f "$WS/secrets.env" ] && source "$WS/secrets.env"
: "${POLICY_CHECKPOINT:?set POLICY_CHECKPOINT}"
export POLICY_HOST="${POLICY_HOST:-127.0.0.1}" POLICY_PORT="${POLICY_PORT:-8765}"
cd "$WS/robots/scripts"
exec python serve_policy.py "$@"
