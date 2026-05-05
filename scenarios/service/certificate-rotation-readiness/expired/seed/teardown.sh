#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCENARIO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../../../.." && pwd)"
NAMESPACE="${SRE_AGENT_TLS_TARGET_NAMESPACE:-edge}"
SERVICE="${SRE_AGENT_TLS_TARGET_SERVICE:-edge-api}"

"$ROOT/harness/tls-target/teardown.sh" "$NAMESPACE" "$SERVICE" "$SCENARIO_DIR/.tmp/coredns-corefile.backup"
