#!/usr/bin/env bash
set -euo pipefail

MODE="${1:?mode is required: resolved or nxdomain}"
HOSTNAME="${2:?hostname is required}"
IP_ADDRESS="${3:-}"
BACKUP_FILE="${4:-}"
TIMEOUT="${SRE_AGENT_COREDNS_ROLLOUT_TIMEOUT:-120s}"

command -v kubectl >/dev/null 2>&1 || { echo "kubectl is required" >&2; exit 127; }

TMP_DIR="$(mktemp -d)"
trap 'rm -rf "$TMP_DIR"' EXIT
CURRENT="$TMP_DIR/Corefile.current"
NEXT="$TMP_DIR/Corefile.next"

kubectl -n kube-system get configmap coredns -o jsonpath='{.data.Corefile}' > "$CURRENT"
if [[ -n "$BACKUP_FILE" && ! -f "$BACKUP_FILE" ]]; then
  mkdir -p "$(dirname "$BACKUP_FILE")"
  cp "$CURRENT" "$BACKUP_FILE"
fi

python3 - "$CURRENT" "$NEXT" "$MODE" "$HOSTNAME" "$IP_ADDRESS" <<'PY'
from __future__ import annotations

import sys

current_path, next_path, mode, hostname, ip_address = sys.argv[1:6]
base = open(current_path, encoding="utf-8").read().rstrip()
marker_start = "# BEGIN sre-agent-coredns-override"
marker_end = "# END sre-agent-coredns-override"
if marker_start in base and marker_end in base:
    before = base.split(marker_start, 1)[0].rstrip()
    after = base.split(marker_end, 1)[1].strip()
    base = "\n\n".join(part for part in (before, after) if part)

if mode == "resolved":
    if not ip_address:
        raise SystemExit("resolved mode requires an IP address")
    block = f"""{marker_start}
example.com:53 {{
    errors
    hosts {{
        {ip_address} {hostname}
    }}
}}
{marker_end}"""
elif mode == "nxdomain":
    block = f"""{marker_start}
example.com:53 {{
    errors
    template IN A {hostname} {{
        rcode NXDOMAIN
    }}
    forward . /etc/resolv.conf
}}
{marker_end}"""
else:
    raise SystemExit(f"unsupported CoreDNS override mode: {mode}")

open(next_path, "w", encoding="utf-8").write(base + "\n\n" + block + "\n")
PY

kubectl -n kube-system create configmap coredns --from-file=Corefile="$NEXT" --dry-run=client -o yaml | kubectl apply -f -
kubectl -n kube-system rollout restart deployment/coredns
kubectl -n kube-system rollout status deployment/coredns --timeout="$TIMEOUT"
