#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
CLUSTER_NAME="${SRE_AGENT_KIND_CLUSTER:-sre-agent-phase-a}"
CONFIG="${SRE_AGENT_KIND_CONFIG:-$ROOT/harness/archetypes/kind/kind-config.yaml}"
KUBECONFIG_PATH="${SRE_AGENT_KIND_KUBECONFIG:-$ROOT/.tmp/kubeconfig-$CLUSTER_NAME}"

command -v kind >/dev/null 2>&1 || { echo "kind is required" >&2; exit 127; }
command -v kubectl >/dev/null 2>&1 || { echo "kubectl is required" >&2; exit 127; }

mkdir -p "$(dirname "$KUBECONFIG_PATH")"
if ! kind get clusters | grep -Fxq "$CLUSTER_NAME"; then
  kind create cluster --name "$CLUSTER_NAME" --config "$CONFIG" --wait "${SRE_AGENT_KIND_WAIT:-120s}"
fi

kind get kubeconfig --name "$CLUSTER_NAME" > "$KUBECONFIG_PATH"
chmod 600 "$KUBECONFIG_PATH"
export KUBECONFIG="$KUBECONFIG_PATH"
kubectl cluster-info >/dev/null
echo "KUBECONFIG=$KUBECONFIG_PATH"
