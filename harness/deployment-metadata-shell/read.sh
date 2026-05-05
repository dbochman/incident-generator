#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 2 ]]; then
  echo "usage: read.sh <namespace> <service-or-deployment> [pod]" >&2
  exit 2
fi

namespace="$1"
service="$2"
pod="${3:-}"
tmp="/tmp/sre-agent-deployment-metadata-read.$$"

cleanup() {
  rm -f "$tmp"
}
trap cleanup EXIT

command -v kubectl >/dev/null 2>&1 || { echo "kubectl is required" >&2; exit 127; }
command -v python3 >/dev/null 2>&1 || { echo "python3 is required" >&2; exit 127; }

if [[ -n "$pod" ]]; then
  replica_set="$(
    kubectl -n "$namespace" get pod "$pod" \
      -o 'jsonpath={.metadata.ownerReferences[?(@.kind=="ReplicaSet")].name}' 2>/dev/null || true
  )"
  if [[ -n "$replica_set" ]]; then
    deployment="$(
      kubectl -n "$namespace" get replicaset "$replica_set" \
        -o 'jsonpath={.metadata.ownerReferences[?(@.kind=="Deployment")].name}' 2>/dev/null || true
    )"
    if [[ -n "$deployment" ]] && kubectl -n "$namespace" get deployment "$deployment" -o json >"$tmp" 2>/dev/null; then
      cat "$tmp"
      exit 0
    fi
  fi
fi

if kubectl -n "$namespace" get deployment "$service" -o json >"$tmp" 2>/dev/null; then
  cat "$tmp"
  exit 0
fi

deployments_json="$(kubectl -n "$namespace" get deployment -l "service=$service" -o json)"
python3 - "$deployments_json" <<'PY'
import json
import sys

loaded = json.loads(sys.argv[1])
items = loaded.get("items") or []
if not items:
    print("no deployment matched service label", file=sys.stderr)
    raise SystemExit(1)

def score(item: dict) -> tuple[int, str, str]:
    metadata = item.get("metadata") or {}
    annotations = metadata.get("annotations") or {}
    name = str(metadata.get("name") or "")
    source = str(annotations.get("sre-agent/deploy-source") or "").lower()
    deploy_time = str(annotations.get("sre-agent/deploy-time") or "")
    canary_score = 1 if source == "canary" or "canary" in name else 0
    return (canary_score, deploy_time, name)

print(json.dumps(max(items, key=score), sort_keys=True))
PY
