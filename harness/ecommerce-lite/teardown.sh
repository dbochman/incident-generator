#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${SRE_AGENT_ECOMMERCE_NAMESPACE:-ecommerce}"
RELEASE="${SRE_AGENT_ECOMMERCE_RELEASE:-ecommerce-lite}"
POSTGRES_RELEASE="${SRE_AGENT_ECOMMERCE_POSTGRES_RELEASE:-checkout-postgres}"
LOADGEN_RELEASE="${SRE_AGENT_ECOMMERCE_LOADGEN_RELEASE:-checkout-postgres-loadgen}"
MESSAGING_SERVICE="${SRE_AGENT_ECOMMERCE_MESSAGING_SERVICE:-ecommerce-lite-messaging}"
MESSAGING_CONFIGMAP="${SRE_AGENT_ECOMMERCE_MESSAGING_CONFIGMAP:-ecommerce-lite-messaging-evidence}"

if command -v helm >/dev/null 2>&1; then
  helm uninstall "$RELEASE" --namespace "$NAMESPACE" >/dev/null 2>&1 || true
  helm uninstall "$LOADGEN_RELEASE" --namespace "$NAMESPACE" >/dev/null 2>&1 || true
  helm uninstall "$POSTGRES_RELEASE" --namespace "$NAMESPACE" >/dev/null 2>&1 || true
fi

if command -v kubectl >/dev/null 2>&1; then
  kubectl -n "$NAMESPACE" delete deployment "$MESSAGING_SERVICE" --ignore-not-found >/dev/null 2>&1 || true
  kubectl -n "$NAMESPACE" delete configmap "$MESSAGING_CONFIGMAP" --ignore-not-found >/dev/null 2>&1 || true
  kubectl delete namespace "$NAMESPACE" --ignore-not-found --wait=false >/dev/null 2>&1 || true
fi
