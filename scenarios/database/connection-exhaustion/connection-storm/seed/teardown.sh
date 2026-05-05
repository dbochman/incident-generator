#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${SRE_AGENT_DATABASE_NAMESPACE:-search}"
POSTGRES_RELEASE="${SRE_AGENT_DATABASE_RELEASE:-search-postgres}"
LOADGEN_RELEASE="${SRE_AGENT_DATABASE_LOADGEN_RELEASE:-search-postgres-loadgen}"

if command -v helm >/dev/null 2>&1; then
  helm uninstall "$LOADGEN_RELEASE" --namespace "$NAMESPACE" >/dev/null 2>&1 || true
  helm uninstall "$POSTGRES_RELEASE" --namespace "$NAMESPACE" >/dev/null 2>&1 || true
fi
if command -v kubectl >/dev/null 2>&1; then
  kubectl delete namespace "$NAMESPACE" --ignore-not-found --wait=false >/dev/null 2>&1 || true
fi
