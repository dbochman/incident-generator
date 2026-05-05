#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCENARIO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../../../.." && pwd)"
NAMESPACE="${SRE_AGENT_DNS_TLS_NAMESPACE:-web}"

"$ROOT/harness/coredns-overrides/restore.sh" "$SCENARIO_DIR/.tmp/coredns-corefile.backup" || true
if command -v kubectl >/dev/null 2>&1; then
  kubectl delete namespace "$NAMESPACE" --ignore-not-found --wait=false >/dev/null 2>&1 || true
fi
