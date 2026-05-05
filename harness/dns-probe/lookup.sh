#!/usr/bin/env bash
set -euo pipefail

HOSTNAME="${1:?hostname is required}"
NAMESPACE="${2:-default}"
PROBE_NAME="${3:-sre-agent-dns-tls-probe}"

command -v kubectl >/dev/null 2>&1 || { echo ";; ->>HEADER<<- opcode: QUERY, status: SERVFAIL, id: 0"; exit 0; }

if ! kubectl -n "$NAMESPACE" get pod "$PROBE_NAME" >/dev/null 2>&1; then
  echo ";; ->>HEADER<<- opcode: QUERY, status: SERVFAIL, id: 0"
  echo ";; probe pod $PROBE_NAME is unavailable in namespace $NAMESPACE"
  exit 0
fi

output="$(kubectl -n "$NAMESPACE" exec "$PROBE_NAME" -- dig +nocmd "$HOSTNAME" A +noall +answer +comments 2>&1 || true)"
if [[ -n "$output" ]]; then
  printf "%s\n" "$output"
else
  echo ";; ->>HEADER<<- opcode: QUERY, status: NXDOMAIN, id: 0"
  echo ";; QUESTION SECTION:"
  echo ";${HOSTNAME}. IN A"
fi
