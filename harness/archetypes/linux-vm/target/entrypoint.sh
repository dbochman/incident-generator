#!/usr/bin/env bash
set -euo pipefail

mkdir -p /var/sre-agent

NODE_EXPORTER_BIN="$(command -v prometheus-node-exporter || command -v node_exporter)"
"$NODE_EXPORTER_BIN" \
  --web.listen-address=:9100 \
  --path.procfs=/host/proc \
  --path.sysfs=/host/sys &

child="$!"
trap 'kill "$child" 2>/dev/null || true; wait "$child" 2>/dev/null || true' TERM INT
wait "$child"
