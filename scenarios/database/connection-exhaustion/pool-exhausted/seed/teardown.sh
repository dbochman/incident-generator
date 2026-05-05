#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${SRE_AGENT_DATABASE_NAMESPACE:-payments}"
POSTGRES_RELEASE="${SRE_AGENT_DATABASE_RELEASE:-checkout-postgres}"
LOADGEN_RELEASE="${SRE_AGENT_DATABASE_LOADGEN_RELEASE:-checkout-postgres-loadgen}"

if command -v helm >/dev/null 2>&1; then
  helm uninstall "$LOADGEN_RELEASE" --namespace "$NAMESPACE" >/dev/null 2>&1 || true
  helm uninstall "$POSTGRES_RELEASE" --namespace "$NAMESPACE" >/dev/null 2>&1 || true
fi
if command -v kubectl >/dev/null 2>&1; then
  kubectl delete namespace "$NAMESPACE" --ignore-not-found --wait=false >/dev/null 2>&1 || true
fi
