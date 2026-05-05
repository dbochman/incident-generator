#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../../../.." && pwd)"
NAMESPACE="${SRE_AGENT_NETWORK_NAMESPACE:-network}"

"$ROOT/harness/chaos-mesh-install.sh"
"$ROOT/harness/shared/seed-helm.sh" payments-network-source "$ROOT/harness/misbehaving-app/chart" "$NAMESPACE" "$SCRIPT_DIR/source-values.yaml"
"$ROOT/harness/shared/seed-helm.sh" payments-network-target "$ROOT/harness/misbehaving-app/chart" "$NAMESPACE" "$SCRIPT_DIR/target-values.yaml"
kubectl apply -f "$SCRIPT_DIR/networkchaos.yaml"
