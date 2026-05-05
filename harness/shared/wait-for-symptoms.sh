#!/usr/bin/env bash
set -euo pipefail

namespace="${SRE_AGENT_SCENARIO_NAMESPACE:-default}"
pod="${SRE_AGENT_SCENARIO_POD:-}"
timeout="${SRE_AGENT_SCENARIO_WAIT_TIMEOUT:-120s}"
predicate="${SRE_AGENT_SCENARIO_SYMPTOM:-pod-pending}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --namespace) namespace="$2"; shift 2 ;;
    --pod) pod="$2"; shift 2 ;;
    --timeout) timeout="$2"; shift 2 ;;
    --predicate) predicate="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

command -v kubectl >/dev/null 2>&1 || { echo "kubectl is required" >&2; exit 127; }

case "$predicate" in
  pod-pending)
    [[ -n "$pod" ]] || { echo "--pod is required for pod-pending" >&2; exit 2; }
    kubectl wait "pod/$pod" -n "$namespace" --for=jsonpath='{.status.phase}'=Pending --timeout="$timeout"
    kubectl describe pod "$pod" -n "$namespace" | grep -E "Insufficient|FailedScheduling|Unschedulable" >/dev/null
    ;;
  *)
    echo "unsupported symptom predicate: $predicate" >&2
    exit 2
    ;;
esac
