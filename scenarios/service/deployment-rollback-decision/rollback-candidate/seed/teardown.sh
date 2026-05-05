#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${SRE_AGENT_ROLLBACK_NAMESPACE:-payments}"
DEPLOYMENT="${SRE_AGENT_ROLLBACK_DEPLOYMENT:-checkout-api}"

if command -v kubectl >/dev/null 2>&1; then
  kubectl -n "$NAMESPACE" delete deployment "$DEPLOYMENT" --ignore-not-found >/dev/null 2>&1 || true
  kubectl delete namespace "$NAMESPACE" --ignore-not-found --wait=false >/dev/null 2>&1 || true
fi
