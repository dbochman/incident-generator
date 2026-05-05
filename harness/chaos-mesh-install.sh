#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAMESPACE="${SRE_AGENT_CHAOS_MESH_NAMESPACE:-chaos-mesh}"
VALUES="$ROOT/harness/observability/values.yaml"
TIMEOUT="${SRE_AGENT_OBSERVABILITY_TIMEOUT:-10m}"

command -v helm >/dev/null 2>&1 || { echo "helm is required" >&2; exit 127; }
command -v kubectl >/dev/null 2>&1 || { echo "kubectl is required" >&2; exit 127; }
command -v python3 >/dev/null 2>&1 || { echo "python3 is required" >&2; exit 127; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

python3 - "$VALUES" > "$WORK/chaos-mesh.yaml" <<'PY'
import sys, yaml
with open(sys.argv[1], encoding="utf-8") as fh:
    values = yaml.safe_load(fh) or {}
section = dict(values.get("chaos-mesh") or {})
section.pop("chart_version", None)
yaml.safe_dump(section, sys.stdout, sort_keys=False)
PY

VERSION="$(python3 - "$VALUES" <<'PY'
import sys, yaml
with open(sys.argv[1], encoding="utf-8") as fh:
    values = yaml.safe_load(fh) or {}
print((values.get("chaos-mesh") or {}).get("chart_version", "2.8.1"))
PY
)"

kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
helm repo add chaos-mesh https://charts.chaos-mesh.org >/dev/null
helm repo update >/dev/null
helm upgrade --install chaos-mesh chaos-mesh/chaos-mesh \
  --namespace "$NAMESPACE" \
  --version "$VERSION" \
  --values "$WORK/chaos-mesh.yaml" \
  --wait --timeout "$TIMEOUT"
