#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${SRE_AGENT_ECOMMERCE_NAMESPACE:-ecommerce}"
RELEASE="${SRE_AGENT_ECOMMERCE_RELEASE:-ecommerce-lite}"

command -v kubectl >/dev/null 2>&1 || { echo "kubectl is required" >&2; exit 127; }

kubectl -n "$NAMESPACE" delete deployment "$RELEASE-loadgen" --ignore-not-found
kubectl -n "$NAMESPACE" delete configmap "$RELEASE-loadgen" --ignore-not-found
