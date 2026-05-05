#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="${SRE_AGENT_KIND_CLUSTER:-sre-agent-phase-a}"
KUBECONFIG_PATH="${SRE_AGENT_KIND_KUBECONFIG:-$(pwd)/.tmp/kubeconfig-$CLUSTER_NAME}"
TUNNEL_PID_PATH="${SRE_AGENT_KIND_TUNNEL_PID:-$KUBECONFIG_PATH.tunnel.pid}"
KEEP_CLUSTER="${SRE_AGENT_KIND_KEEP_CLUSTER:-0}"

if [[ "$KEEP_CLUSTER" == "1" ]]; then
  echo "Keeping kind cluster '$CLUSTER_NAME' because SRE_AGENT_KIND_KEEP_CLUSTER=1"
elif command -v kind >/dev/null 2>&1 && kind get clusters | grep -Fxq "$CLUSTER_NAME"; then
  kind delete cluster --name "$CLUSTER_NAME"
fi
if [[ -f "$TUNNEL_PID_PATH" ]]; then
  TUNNEL_PID="$(cat "$TUNNEL_PID_PATH" 2>/dev/null || true)"
  if [[ -n "$TUNNEL_PID" ]]; then
    kill "$TUNNEL_PID" 2>/dev/null || true
  fi
fi
rm -f "$KUBECONFIG_PATH"
rm -f "$TUNNEL_PID_PATH"
