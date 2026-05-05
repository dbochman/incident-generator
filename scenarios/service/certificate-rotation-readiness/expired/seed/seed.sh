#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCENARIO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../../../.." && pwd)"
NAMESPACE="${SRE_AGENT_TLS_TARGET_NAMESPACE:-edge}"
SERVICE="${SRE_AGENT_TLS_TARGET_SERVICE:-edge-api}"
HOSTNAME="${SRE_AGENT_TLS_TARGET_HOSTNAME:-expired.example.com}"
TMP_DIR="$SCENARIO_DIR/.tmp"

mkdir -p "$TMP_DIR"
"$ROOT/harness/tls-target/apply.sh" \
  "$NAMESPACE" \
  "$SERVICE" \
  "$SERVICE" \
  "$HOSTNAME" \
  "$HOSTNAME" \
  "DNS:$HOSTNAME" \
  0 \
  "$TMP_DIR/coredns-corefile.backup"
