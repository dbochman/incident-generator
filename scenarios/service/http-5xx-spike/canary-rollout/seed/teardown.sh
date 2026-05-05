#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCENARIO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
NAMESPACE="${SRE_AGENT_MISBEHAVING_APP_NAMESPACE:-payments}"
TMP_DIR="$SCENARIO_DIR/.tmp"
PID_FILE="$TMP_DIR/checkout-api-canary.port-forward.pid"

if [[ -s "$PID_FILE" ]]; then
  pid="$(cat "$PID_FILE")"
  if kill -0 "$pid" >/dev/null 2>&1; then
    kill "$pid" >/dev/null 2>&1 || true
  fi
  rm -f "$PID_FILE"
fi

if command -v helm >/dev/null 2>&1; then
  helm uninstall checkout-api-canary --namespace "$NAMESPACE" >/dev/null 2>&1 || true
  helm uninstall checkout-api-stable --namespace "$NAMESPACE" >/dev/null 2>&1 || true
fi
if command -v kubectl >/dev/null 2>&1; then
  kubectl delete namespace "$NAMESPACE" --ignore-not-found --wait=false >/dev/null 2>&1 || true
fi

