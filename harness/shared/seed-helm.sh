#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 4 ]]; then
  echo "usage: seed-helm.sh <release> <chart> <namespace> <values.yaml> [-- extra helm args]" >&2
  exit 2
fi

release="$1"
chart="$2"
namespace="$3"
values="$4"
shift 4

command -v helm >/dev/null 2>&1 || { echo "helm is required" >&2; exit 127; }
command -v kubectl >/dev/null 2>&1 || { echo "kubectl is required" >&2; exit 127; }

kubectl create namespace "$namespace" --dry-run=client -o yaml | kubectl apply -f -
helm upgrade --install "$release" "$chart" \
  --namespace "$namespace" \
  --values "$values" \
  --wait \
  --timeout "${SRE_AGENT_HELM_TIMEOUT:-5m}" \
  "$@"
