#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
CLUSTER_NAME="${SRE_AGENT_KIND_CLUSTER:-sre-agent-phase-a}"
CONFIG="${SRE_AGENT_KIND_CONFIG:-$ROOT/harness/archetypes/kind/kind-config.yaml}"
KUBECONFIG_PATH="${SRE_AGENT_KIND_KUBECONFIG:-$ROOT/.tmp/kubeconfig-$CLUSTER_NAME}"
TUNNEL_PID_PATH="${SRE_AGENT_KIND_TUNNEL_PID:-$KUBECONFIG_PATH.tunnel.pid}"
WAIT="${SRE_AGENT_KIND_WAIT:-120s}"
API_WAIT_SECONDS="${SRE_AGENT_KIND_API_WAIT_SECONDS:-120}"
CREATE_TIMEOUT_SECONDS="${SRE_AGENT_KIND_CREATE_TIMEOUT_SECONDS:-300}"

command -v kind >/dev/null 2>&1 || { echo "kind is required" >&2; exit 127; }
command -v kubectl >/dev/null 2>&1 || { echo "kubectl is required" >&2; exit 127; }

remote_docker_ssh_target() {
  local docker_host="${DOCKER_HOST:-}"
  if [[ "$docker_host" == ssh://* ]]; then
    printf "%s" "${docker_host#ssh://}"
  fi
}

start_remote_api_tunnel() {
  local ssh_target="$1"
  local server="$2"
  local port=""

  if [[ "$server" =~ ^https://(127\.0\.0\.1|localhost):([0-9]+)$ ]]; then
    port="${BASH_REMATCH[2]}"
  else
    return 0
  fi

  if [[ -f "$TUNNEL_PID_PATH" ]]; then
    local existing_pid
    existing_pid="$(cat "$TUNNEL_PID_PATH" 2>/dev/null || true)"
    if [[ -n "$existing_pid" ]] && kill -0 "$existing_pid" 2>/dev/null; then
      return 0
    fi
  fi

  ssh -N -o ExitOnForwardFailure=yes -L "$port:127.0.0.1:$port" "$ssh_target" </dev/null >/dev/null 2>&1 &
  local tunnel_pid=$!
  echo "$tunnel_pid" > "$TUNNEL_PID_PATH"

  local deadline=$((SECONDS + 20))
  until (echo > "/dev/tcp/127.0.0.1/$port") >/dev/null 2>&1; do
    if (( SECONDS >= deadline )); then
      kill "$tunnel_pid" 2>/dev/null || true
      rm -f "$TUNNEL_PID_PATH"
      echo "timed out opening remote kind API tunnel on localhost:$port" >&2
      return 1
    fi
    sleep 1
  done
}

wait_for_cluster_info() {
  local deadline=$((SECONDS + API_WAIT_SECONDS))
  until kubectl cluster-info >/dev/null 2>&1; do
    if (( SECONDS >= deadline )); then
      kubectl cluster-info >/dev/null
      return 1
    fi
    sleep 2
  done
}

write_remote_kubeconfig() {
  local host_port
  local cluster_ref

  host_port="$(docker inspect "$CLUSTER_NAME-control-plane" --format '{{(index (index .NetworkSettings.Ports "6443/tcp") 0).HostPort}}')"
  docker exec "$CLUSTER_NAME-control-plane" cat /etc/kubernetes/admin.conf > "$KUBECONFIG_PATH"
  chmod 600 "$KUBECONFIG_PATH"
  cluster_ref="$(kubectl config view --kubeconfig "$KUBECONFIG_PATH" --minify -o jsonpath='{.contexts[0].context.cluster}')"
  kubectl config set-cluster "$cluster_ref" \
    --kubeconfig "$KUBECONFIG_PATH" \
    --server="https://127.0.0.1:$host_port" >/dev/null
}

mkdir -p "$(dirname "$KUBECONFIG_PATH")"
REMOTE_SSH_TARGET="$(remote_docker_ssh_target)"
CREATE_WAIT="$WAIT"
if [[ -n "$REMOTE_SSH_TARGET" ]]; then
  CREATE_WAIT="0s"
fi

if ! kind get clusters | grep -Fxq "$CLUSTER_NAME"; then
  set +e
  timeout "${CREATE_TIMEOUT_SECONDS}s" kind create cluster --name "$CLUSTER_NAME" --config "$CONFIG" --wait "$CREATE_WAIT"
  CREATE_STATUS=$?
  set -e
  if [[ "$CREATE_STATUS" -eq 124 ]]; then
    if [[ -n "$REMOTE_SSH_TARGET" ]] && kind get clusters | grep -Fxq "$CLUSTER_NAME"; then
      echo "kind create timed out after ${CREATE_TIMEOUT_SECONDS}s, but cluster '$CLUSTER_NAME' exists; continuing with readiness checks" >&2
    else
      echo "timed out after ${CREATE_TIMEOUT_SECONDS}s creating kind cluster '$CLUSTER_NAME'" >&2
      exit "$CREATE_STATUS"
    fi
  elif [[ "$CREATE_STATUS" -ne 0 ]]; then
    exit "$CREATE_STATUS"
  fi
fi

if [[ -n "$REMOTE_SSH_TARGET" ]]; then
  write_remote_kubeconfig
else
  kind get kubeconfig --name "$CLUSTER_NAME" > "$KUBECONFIG_PATH"
  chmod 600 "$KUBECONFIG_PATH"
fi
export KUBECONFIG="$KUBECONFIG_PATH"
if [[ -n "$REMOTE_SSH_TARGET" ]]; then
  SERVER="$(kubectl config view --kubeconfig "$KUBECONFIG_PATH" --minify -o jsonpath='{.clusters[0].cluster.server}')"
  start_remote_api_tunnel "$REMOTE_SSH_TARGET" "$SERVER"
fi
wait_for_cluster_info
kubectl wait --for=condition=Ready nodes --all --timeout "$WAIT" >/dev/null
echo "KUBECONFIG=$KUBECONFIG_PATH"
