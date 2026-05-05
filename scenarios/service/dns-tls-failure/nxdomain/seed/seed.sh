#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCENARIO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../../../.." && pwd)"
NAMESPACE="${SRE_AGENT_DNS_TLS_NAMESPACE:-web}"
HOSTNAME="${SRE_AGENT_DNS_TLS_HOSTNAME:-checkout.example.com}"
TMP_DIR="$SCENARIO_DIR/.tmp"

mkdir -p "$TMP_DIR"
"$ROOT/harness/dns-probe/apply.sh" "$NAMESPACE"
"$ROOT/harness/coredns-overrides/apply.sh" nxdomain "$HOSTNAME" "" "$TMP_DIR/coredns-corefile.backup"
