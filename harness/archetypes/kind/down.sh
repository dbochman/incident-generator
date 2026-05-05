#!/usr/bin/env bash
set -euo pipefail

CLUSTER_NAME="${SRE_AGENT_KIND_CLUSTER:-sre-agent-phase-a}"
KUBECONFIG_PATH="${SRE_AGENT_KIND_KUBECONFIG:-$(pwd)/.tmp/kubeconfig-$CLUSTER_NAME}"

if command -v kind >/dev/null 2>&1 && kind get clusters | grep -Fxq "$CLUSTER_NAME"; then
  kind delete cluster --name "$CLUSTER_NAME"
fi
rm -f "$KUBECONFIG_PATH"
