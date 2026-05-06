#!/usr/bin/env bash
set -euo pipefail

mkdir -p /var/sre-agent

NODE_EXPORTER_BIN="$(command -v prometheus-node-exporter || command -v node_exporter)"
"$NODE_EXPORTER_BIN" \
  --web.listen-address=:9100 \
  --path.procfs=/host/proc \
  --path.sysfs=/host/sys &

node_exporter_pid="$!"
/usr/local/bin/sre-agent-app-host-lite.sh &
app_host_pid="$!"

cleanup() {
  kill "$node_exporter_pid" "$app_host_pid" 2>/dev/null || true
  wait "$node_exporter_pid" "$app_host_pid" 2>/dev/null || true
}

trap cleanup TERM INT EXIT
wait -n "$node_exporter_pid" "$app_host_pid"
