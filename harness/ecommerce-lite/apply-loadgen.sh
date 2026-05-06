#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SCRIPT_DIR="$ROOT/harness/ecommerce-lite"
NAMESPACE="${SRE_AGENT_ECOMMERCE_NAMESPACE:-ecommerce}"
RELEASE="${SRE_AGENT_ECOMMERCE_RELEASE:-ecommerce-lite}"
TIMEOUT="${SRE_AGENT_ECOMMERCE_TIMEOUT:-5m}"
WARMUP_SECONDS="${SRE_AGENT_ECOMMERCE_LOADGEN_WARMUP_SECONDS:-60}"

command -v kubectl >/dev/null 2>&1 || { echo "kubectl is required" >&2; exit 127; }
command -v helm >/dev/null 2>&1 || { echo "helm is required" >&2; exit 127; }

python3 "$SCRIPT_DIR/loadgen-preview.py" \
  --values "$SCRIPT_DIR/chart/values.yaml" \
  --release "$RELEASE" \
  --namespace "$NAMESPACE" \
  --limit "${SRE_AGENT_ECOMMERCE_LOADGEN_PREVIEW_REQUESTS:-30}" \
  > "${SRE_AGENT_ECOMMERCE_LOADGEN_PREVIEW:-/tmp/ecommerce-lite-loadgen-preview.json}"

"$ROOT/harness/shared/seed-helm.sh" \
  "$RELEASE" \
  "$SCRIPT_DIR/chart" \
  "$NAMESPACE" \
  "$SCRIPT_DIR/loadgen-values.yaml"

kubectl -n "$NAMESPACE" rollout status "deployment/$RELEASE-loadgen" --timeout="$TIMEOUT"
sleep "$WARMUP_SECONDS"
echo "ecommerce-lite load generator warmup complete release=$RELEASE namespace=$NAMESPACE warmup_seconds=$WARMUP_SECONDS"
