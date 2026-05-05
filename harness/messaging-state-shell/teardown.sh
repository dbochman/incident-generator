#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${1:?namespace is required}"
SERVICE="${2:?service is required}"
CONFIGMAP="${3:-sre-agent-messaging-evidence}"

if command -v kubectl >/dev/null 2>&1; then
  kubectl -n "$NAMESPACE" delete deployment "$SERVICE" --ignore-not-found >/dev/null 2>&1 || true
  kubectl -n "$NAMESPACE" delete configmap "$CONFIGMAP" --ignore-not-found >/dev/null 2>&1 || true
  kubectl delete namespace "$NAMESPACE" --ignore-not-found --wait=false >/dev/null 2>&1 || true
fi
