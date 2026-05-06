#!/usr/bin/env bash
set -euo pipefail

RUN_DIR="${SRE_AGENT_APP_HOST_RUN_DIR:-/run/sre-agent/app-host-lite}"
HEALTH_FILE="$RUN_DIR/health"
MAX_AGE_SECONDS="${SRE_AGENT_APP_HOST_HEALTH_MAX_AGE_SECONDS:-20}"

[[ -f "$HEALTH_FILE" ]] || { echo "missing app-host-lite health file" >&2; exit 1; }

last_update="$(cat "$HEALTH_FILE")"
[[ "$last_update" =~ ^[0-9]+$ ]] || { echo "invalid app-host-lite health timestamp" >&2; exit 1; }

now="$(date +%s)"
age=$((now - last_update))
if [[ "$age" -gt "$MAX_AGE_SECONDS" ]]; then
  echo "stale app-host-lite health timestamp age=${age}s" >&2
  exit 1
fi

if [[ -f "$RUN_DIR/supervisor.pid" ]]; then
  supervisor_pid="$(cat "$RUN_DIR/supervisor.pid")"
  [[ "$supervisor_pid" =~ ^[0-9]+$ ]] || { echo "invalid supervisor pid" >&2; exit 1; }
  kill -0 "$supervisor_pid" 2>/dev/null || { echo "app-host-lite supervisor is not running" >&2; exit 1; }
fi

exit 0
