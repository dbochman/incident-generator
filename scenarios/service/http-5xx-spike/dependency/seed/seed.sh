#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCENARIO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../../../.." && pwd)"
NAMESPACE="${SRE_AGENT_MISBEHAVING_APP_NAMESPACE:-search}"
RELEASE="${SRE_AGENT_MISBEHAVING_APP_RELEASE:-search-api}"
TIMEOUT="${SRE_AGENT_MISBEHAVING_APP_HELM_TIMEOUT:-3m}"
LOCAL_PORT="${SRE_AGENT_MISBEHAVING_APP_PORT:-18081}"
CURL_CONNECT_TIMEOUT="${SRE_AGENT_SEED_CURL_CONNECT_TIMEOUT:-2}"
CURL_MAX_TIME="${SRE_AGENT_SEED_CURL_MAX_TIME:-5}"
TMP_DIR="$SCENARIO_DIR/.tmp"
PID_FILE="$TMP_DIR/$RELEASE.port-forward.pid"
LOG_FILE="$TMP_DIR/$RELEASE.port-forward.log"

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

helm upgrade --install "$RELEASE" "$ROOT/harness/misbehaving-app/chart" \
  --namespace "$NAMESPACE" \
  --create-namespace \
  --values "$SCRIPT_DIR/values.yaml" \
  --wait --timeout "$TIMEOUT"

kubectl -n "$NAMESPACE" rollout status "deploy/$RELEASE" --timeout="$TIMEOUT"
kubectl -n "$NAMESPACE" port-forward "svc/$RELEASE" "$LOCAL_PORT:8080" >"$LOG_FILE" 2>&1 &
echo "$!" > "$PID_FILE"

for _ in $(seq 1 30); do
  if curl --connect-timeout "$CURL_CONNECT_TIMEOUT" --max-time "$CURL_MAX_TIME" -fsS "http://127.0.0.1:$LOCAL_PORT/healthz" >/dev/null; then
    break
  fi
  sleep 1
done
curl --connect-timeout "$CURL_CONNECT_TIMEOUT" --max-time "$CURL_MAX_TIME" -fsS "http://127.0.0.1:$LOCAL_PORT/healthz" >/dev/null

for index in $(seq 0 9); do
  curl --connect-timeout "$CURL_CONNECT_TIMEOUT" --max-time "$CURL_MAX_TIME" -sS -o /dev/null "http://127.0.0.1:$LOCAL_PORT/api/v1/search/order-$index" || true
done
curl --connect-timeout "$CURL_CONNECT_TIMEOUT" --max-time "$CURL_MAX_TIME" -sS -o /dev/null "http://127.0.0.1:$LOCAL_PORT/api/v1/search/live-dependency-0" || true
