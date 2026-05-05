#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${SRE_AGENT_NETWORK_NAMESPACE:-network}"

if command -v kubectl >/dev/null 2>&1; then
  kubectl -n "$NAMESPACE" delete networkchaos checkout-cross-az-loss --ignore-not-found >/dev/null 2>&1 || true
fi
if command -v helm >/dev/null 2>&1; then
  helm uninstall checkout-network-target --namespace "$NAMESPACE" >/dev/null 2>&1 || true
  helm uninstall checkout-network-source --namespace "$NAMESPACE" >/dev/null 2>&1 || true
fi
if command -v kubectl >/dev/null 2>&1; then
  kubectl delete namespace "$NAMESPACE" --ignore-not-found --wait=false >/dev/null 2>&1 || true
fi
