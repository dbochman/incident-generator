#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
NAMESPACE="${SRE_AGENT_OBSERVABILITY_NAMESPACE:-observability}"
VALUES="$ROOT/harness/observability/values.yaml"
TIMEOUT="${SRE_AGENT_OBSERVABILITY_TIMEOUT:-10m}"

command -v helm >/dev/null 2>&1 || { echo "helm is required" >&2; exit 127; }
command -v kubectl >/dev/null 2>&1 || { echo "kubectl is required" >&2; exit 127; }
command -v python3 >/dev/null 2>&1 || { echo "python3 is required" >&2; exit 127; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# Extract a single chart's values section from the keyed values.yaml,
# stripping the chart_version meta-key, and write to a per-chart file
# so helm only sees the keys its chart actually understands.
extract_section() {
  local key="$1"
  local out="$2"
  python3 - "$VALUES" "$key" > "$out" <<'PY'
import sys, yaml
src, key = sys.argv[1], sys.argv[2]
with open(src) as fh:
    full = yaml.safe_load(fh) or {}
section = full.get(key) or {}
if isinstance(section, dict):
    section = {k: v for k, v in section.items() if k != "chart_version"}
yaml.safe_dump(section, sys.stdout, sort_keys=False)
PY
}

chart_version() {
  local key="$1"
  python3 -c "import yaml; print(yaml.safe_load(open('$VALUES'))['$key']['chart_version'])"
}

kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null
helm repo add grafana https://grafana.github.io/helm-charts >/dev/null
helm repo add open-telemetry https://open-telemetry.github.io/opentelemetry-helm-charts >/dev/null
if [[ "${SRE_AGENT_INSTALL_CHAOS_MESH:-0}" == "1" ]]; then
  helm repo add chaos-mesh https://charts.chaos-mesh.org >/dev/null
fi
helm repo update >/dev/null

extract_section kube-prometheus-stack "$WORK/kube-prometheus-stack.yaml"
extract_section loki-stack "$WORK/loki-stack.yaml"
extract_section tempo "$WORK/tempo.yaml"
extract_section opentelemetry-collector "$WORK/opentelemetry-collector.yaml"

helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --namespace "$NAMESPACE" \
  --version "$(chart_version kube-prometheus-stack)" \
  --values "$WORK/kube-prometheus-stack.yaml" \
  --wait --timeout "$TIMEOUT"

helm upgrade --install loki grafana/loki-stack \
  --namespace "$NAMESPACE" \
  --version "$(chart_version loki-stack)" \
  --values "$WORK/loki-stack.yaml" \
  --wait --timeout "$TIMEOUT"

helm upgrade --install tempo grafana/tempo \
  --namespace "$NAMESPACE" \
  --version "$(chart_version tempo)" \
  --values "$WORK/tempo.yaml" \
  --wait --timeout "$TIMEOUT"

helm upgrade --install otel open-telemetry/opentelemetry-collector \
  --namespace "$NAMESPACE" \
  --version "$(chart_version opentelemetry-collector)" \
  --values "$WORK/opentelemetry-collector.yaml" \
  --wait --timeout "$TIMEOUT"

if [[ "${SRE_AGENT_INSTALL_CHAOS_MESH:-0}" == "1" ]]; then
  "$ROOT/harness/chaos-mesh-install.sh"
fi

FAKE_PD_IMAGE="sre-agent/fake-pagerduty:local"
MISBEHAVING_APP_IMAGE="sre-agent/misbehaving-app:local"
docker build -t "$FAKE_PD_IMAGE" "$ROOT/harness/observability/fake-pagerduty"
docker build -t "$MISBEHAVING_APP_IMAGE" "$ROOT/harness/misbehaving-app"

# When the helm install targets a kind cluster, the locally-built image must
# be loaded into the cluster's containerd; otherwise the deployment hits
# ImagePullBackOff because the image is not on any registry. Auto-detect kind
# from the current kubectl context name (kind sets it to "kind-<cluster>").
KIND_CONTEXT="$(kubectl config current-context 2>/dev/null || true)"
if [[ "$KIND_CONTEXT" == kind-* ]] && command -v kind >/dev/null 2>&1; then
  CLUSTER_NAME="${KIND_CONTEXT#kind-}"
  kind load docker-image "$FAKE_PD_IMAGE" --name "$CLUSTER_NAME"
  kind load docker-image "$MISBEHAVING_APP_IMAGE" --name "$CLUSTER_NAME"
fi

helm upgrade --install fake-pagerduty "$ROOT/harness/observability/fake-pagerduty/chart" \
  --namespace "$NAMESPACE" \
  --wait --timeout "$TIMEOUT"
