#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCENARIO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../../../.." && pwd)"
NAMESPACE="${SRE_AGENT_MISBEHAVING_APP_NAMESPACE:-identity}"
TIMEOUT="${SRE_AGENT_MISBEHAVING_APP_HELM_TIMEOUT:-3m}"
LOCAL_PORT="${SRE_AGENT_MISBEHAVING_APP_PORT:-18083}"
TMP_DIR="$SCENARIO_DIR/.tmp"
PID_FILE="$TMP_DIR/profile-api-canary.port-forward.pid"
LOG_FILE="$TMP_DIR/profile-api-canary.port-forward.log"

command -v helm >/dev/null 2>&1 || { echo "helm is required" >&2; exit 127; }
command -v kubectl >/dev/null 2>&1 || { echo "kubectl is required" >&2; exit 127; }
command -v curl >/dev/null 2>&1 || { echo "curl is required" >&2; exit 127; }

mkdir -p "$TMP_DIR"
if [[ -s "$PID_FILE" ]]; then
  old_pid="$(cat "$PID_FILE")"
  if kill -0 "$old_pid" >/dev/null 2>&1; then
    kill "$old_pid" >/dev/null 2>&1 || true
  fi
  rm -f "$PID_FILE"
fi

helm upgrade --install profile-api-stable "$ROOT/harness/misbehaving-app/chart" \
  --namespace "$NAMESPACE" \
  --create-namespace \
  --values "$SCRIPT_DIR/stable-values.yaml" \
  --wait --timeout "$TIMEOUT"

helm upgrade --install profile-api-canary "$ROOT/harness/misbehaving-app/chart" \
  --namespace "$NAMESPACE" \
  --create-namespace \
  --values "$SCRIPT_DIR/values.yaml" \
  --wait --timeout "$TIMEOUT"

kubectl -n "$NAMESPACE" rollout status deploy/profile-api-canary --timeout="$TIMEOUT"
kubectl -n "$NAMESPACE" port-forward svc/profile-api-canary "$LOCAL_PORT:8080" >"$LOG_FILE" 2>&1 &
echo "$!" > "$PID_FILE"

for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:$LOCAL_PORT/healthz" >/dev/null; then
    break
  fi
  sleep 1
done
curl -fsS "http://127.0.0.1:$LOCAL_PORT/healthz" >/dev/null

for index in $(seq 0 39); do
  curl -sS -o /dev/null "http://127.0.0.1:$LOCAL_PORT/api/v1/profile/order-$index" || true
done
curl -sS -o /dev/null "http://127.0.0.1:$LOCAL_PORT/api/v1/profile/live-latency-deploy-0" || true

