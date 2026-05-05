#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
NAMESPACE="${SRE_AGENT_OBSERVABILITY_NAMESPACE:-observability}"
VALUES="$ROOT/harness/observability/values.yaml"
TIMEOUT="${SRE_AGENT_OBSERVABILITY_TIMEOUT:-10m}"
FAKE_PD_IMAGE="sre-agent/fake-pagerduty:local"
MISBEHAVING_APP_IMAGE="sre-agent/misbehaving-app:local"
LOCAL_IMAGES_STAMP="sre-agent-local-images"

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

kind_cluster_name() {
  local cluster
  local context
  local nodes

  if [[ -n "${SRE_AGENT_KIND_CLUSTER:-}" ]]; then
    printf "%s" "$SRE_AGENT_KIND_CLUSTER"
    return 0
  fi
  context="$(kubectl config current-context 2>/dev/null || true)"
  if [[ "$context" == kind-* ]]; then
    printf "%s" "${context#kind-}"
    return 0
  fi
  command -v kind >/dev/null 2>&1 || return 1
  if [[ "$context" == *@* ]]; then
    cluster="${context##*@}"
    if kind get clusters 2>/dev/null | grep -Fxq "$cluster"; then
      printf "%s" "$cluster"
      return 0
    fi
  fi
  nodes="$(kubectl get nodes -o 'jsonpath={range .items[*]}{.metadata.name}{"\n"}{end}' 2>/dev/null || true)"
  [[ -n "$nodes" ]] || return 1
  for cluster in $(kind get clusters 2>/dev/null || true); do
    if grep -Fxq "${cluster}-control-plane" <<<"$nodes"; then
      printf "%s" "$cluster"
      return 0
    fi
  done
  return 1
}

kind_image_present() {
  local cluster_name="$1"
  local image="$2"
  local image_without_tag="${image%%:*}"
  local node
  local nodes

  command -v kind >/dev/null 2>&1 || return 1
  nodes="$(kind get nodes --name "$cluster_name" 2>/dev/null)" || return 1
  [[ -n "$nodes" ]] || return 1
  for node in $nodes; do
    docker exec "$node" crictl images 2>/dev/null | grep -Fq "docker.io/$image_without_tag" || return 1
  done
}

observability_ready() {
  local release
  local cluster_name
  kubectl get namespace "$NAMESPACE" >/dev/null 2>&1 || return 1
  for release in kube-prometheus-stack loki tempo otel fake-pagerduty; do
    helm status "$release" --namespace "$NAMESPACE" >/dev/null 2>&1 || return 1
  done
  kubectl get pods --namespace "$NAMESPACE" --field-selector=status.phase!=Succeeded -o json |
    python3 -c 'import json, sys
data = json.load(sys.stdin)
bad = []
items = data.get("items", [])
if not items:
    bad.append("no-pods")
for pod in items:
    meta = pod.get("metadata") or {}
    status = pod.get("status") or {}
    phase = status.get("phase")
    containers = status.get("containerStatuses") or []
    if phase != "Running" or not containers or not all(c.get("ready") for c in containers):
        bad.append("%s:%s" % (meta.get("name", "unknown"), phase))
if bad:
    print("not ready: " + ", ".join(bad), file=sys.stderr)
    sys.exit(1)' || return 1
  cluster_name="$(kind_cluster_name)"
  if [[ -n "$cluster_name" && "${SRE_AGENT_OBSERVABILITY_VERIFY_IMAGES:-0}" == "1" ]]; then
    kind_image_present "$cluster_name" "sre-agent/fake-pagerduty:local" || return 1
    kind_image_present "$cluster_name" "sre-agent/misbehaving-app:local" || return 1
  fi
}

local_images_stamped() {
  local fake_pd
  local misbehaving_app
  fake_pd="$(kubectl -n "$NAMESPACE" get configmap "$LOCAL_IMAGES_STAMP" -o 'jsonpath={.data.fake_pagerduty}' 2>/dev/null || true)"
  misbehaving_app="$(kubectl -n "$NAMESPACE" get configmap "$LOCAL_IMAGES_STAMP" -o 'jsonpath={.data.misbehaving_app}' 2>/dev/null || true)"
  [[ "$fake_pd" == "$FAKE_PD_IMAGE" && "$misbehaving_app" == "$MISBEHAVING_APP_IMAGE" ]]
}

stamp_local_images() {
  kubectl -n "$NAMESPACE" create configmap "$LOCAL_IMAGES_STAMP" \
    --from-literal="fake_pagerduty=$FAKE_PD_IMAGE" \
    --from-literal="misbehaving_app=$MISBEHAVING_APP_IMAGE" \
    --dry-run=client -o yaml | kubectl apply -f - >/dev/null
}

if [[ "${SRE_AGENT_OBSERVABILITY_REUSE_READY:-0}" == "1" ]] && observability_ready; then
  echo "Reusing ready observability stack in namespace '$NAMESPACE'"
  exit 0
fi

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

build_image() {
  local image="$1"
  local context="$2"
  local docker_host="${DOCKER_HOST:-}"

  if [[ "$docker_host" == ssh://* ]]; then
    local ssh_target="${docker_host#ssh://}"
    tar -C "$context" -cf - . | ssh "$ssh_target" \
      "tmpdir=\$(mktemp -d); trap 'rm -rf \"\$tmpdir\"' EXIT; DOCKER_CONFIG=\"\$tmpdir\" DOCKER_BUILDKIT=0 docker build --pull=false -t \"$image\" -"
    return
  fi

  DOCKER_BUILDKIT="${DOCKER_BUILDKIT:-0}" docker build --pull=false -t "$image" "$context"
}

load_kind_image() {
  local image="$1"
  local cluster_name="$2"
  local docker_host="${DOCKER_HOST:-}"

  if [[ "$docker_host" == ssh://* ]]; then
    local ssh_target="${docker_host#ssh://}"
    ssh "$ssh_target" bash -s -- "$image" "$cluster_name" <<'REMOTE'
set -euo pipefail
image="$1"
cluster_name="$2"
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

docker image inspect "$image" >/dev/null
docker save -o "$tmpdir/image.tar" "$image"
nodes="$(docker ps -a --filter "label=io.x-k8s.kind.cluster=$cluster_name" --format '{{.Names}}')"
if [[ -z "$nodes" ]]; then
  echo "no kind nodes found for cluster $cluster_name" >&2
  exit 1
fi
for node in $nodes; do
  docker exec --privileged -i "$node" \
    ctr --namespace=k8s.io images import --all-platforms - < "$tmpdir/image.tar"
done
REMOTE
    return
  fi

  kind load docker-image "$image" --name "$cluster_name"
}

if [[ "${SRE_AGENT_OBSERVABILITY_REUSE_READY:-0}" == "1" ]] && local_images_stamped; then
  echo "Reusing previously loaded local harness images"
else
  build_image "$FAKE_PD_IMAGE" "$ROOT/harness/observability/fake-pagerduty"
  build_image "$MISBEHAVING_APP_IMAGE" "$ROOT/harness/misbehaving-app"

  # When the helm install targets a kind cluster, the locally-built image must
  # be loaded into the cluster's containerd; otherwise the deployment hits
  # ImagePullBackOff because the image is not on any registry. Remote Docker
  # kubeconfigs do not always preserve kind's "kind-<cluster>" context name, so
  # fall back to matching the current Kubernetes nodes to known kind clusters.
  if CLUSTER_NAME="$(kind_cluster_name)"; then
    load_kind_image "$FAKE_PD_IMAGE" "$CLUSTER_NAME"
    load_kind_image "$MISBEHAVING_APP_IMAGE" "$CLUSTER_NAME"
  fi
  stamp_local_images
fi

helm upgrade --install fake-pagerduty "$ROOT/harness/observability/fake-pagerduty/chart" \
  --namespace "$NAMESPACE" \
  --wait --timeout "$TIMEOUT"
