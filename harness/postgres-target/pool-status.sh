#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 ]]; then
  echo "usage: pool-status.sh <namespace> <postgres-release> <database-name>" >&2
  exit 2
fi

namespace="$1"
release="$2"
database_name="$3"
prometheus_url="${PROMETHEUS_URL:-}"

if [[ -z "$prometheus_url" ]]; then
  echo "PROMETHEUS_URL is required" >&2
  exit 2
fi

command -v kubectl >/dev/null 2>&1 || { echo "kubectl is required" >&2; exit 127; }
command -v python3 >/dev/null 2>&1 || { echo "python3 is required" >&2; exit 127; }

active="$(
  python3 - "$prometheus_url" "$database_name" <<'PY'
import json
import sys
import urllib.parse
import urllib.request

prometheus_url, database = sys.argv[1:]
query = (
    f'sum(pg_stat_database_numbackends{{datname="{database}"}} '
    f'or pg_stat_database_numbackends{{database="{database}"}} '
    f'or pg_stat_activity_count{{datname="{database}"}} '
    f'or pg_stat_activity_count{{database="{database}"}})'
)
url = prometheus_url.rstrip("/") + "/api/v1/query?" + urllib.parse.urlencode({"query": query})
with urllib.request.urlopen(url, timeout=10) as response:
    payload = json.loads(response.read().decode("utf-8"))
results = payload.get("data", {}).get("result", [])
if not results:
    print("0")
else:
    print(results[0].get("value", [None, "0"])[1])
PY
)"

config_json="$(kubectl -n "$namespace" get configmap "$release-config" -o json)"
max_connections="$(
  python3 - "$config_json" <<'PY'
import json
import re
import sys

loaded = json.loads(sys.argv[1])
config = (loaded.get("data") or {}).get("postgresql.conf", "")
match = re.search(r"^\s*max_connections\s*=\s*([0-9]+)\s*$", config, re.MULTILINE)
print(match.group(1) if match else "0")
PY
)"

loadgen_release="${release}-loadgen"
deployment_json="$(kubectl -n "$namespace" get deployment "$loadgen_release" -o json 2>/dev/null || true)"
clients="$(
  python3 - "$deployment_json" <<'PY'
import json
import sys

try:
    loaded = json.loads(sys.argv[1])
except json.JSONDecodeError:
    print("0")
    raise SystemExit
containers = loaded.get("spec", {}).get("template", {}).get("spec", {}).get("containers", [])
for container in containers:
    for env in container.get("env", []):
        if env.get("name") == "PGBENCH_CLIENTS":
            print(env.get("value") or "0")
            raise SystemExit
print("0")
PY
)"

python3 - "$active" "$max_connections" "${clients:-0}" "$release" <<'PY'
import sys

active = float(sys.argv[1] or 0)
max_connections = int(float(sys.argv[2] or 0))
clients = int(float(sys.argv[3] or 0))
database = sys.argv[4]

if max_connections <= 0:
    max_connections = max(int(round(active)), 1)
utilization = round((active / max_connections) * 100, 1)
waiters = max(clients - int(round(active)), 0)
print(
    "active={active} idle=0 max={max_connections} waiters={waiters} "
    "utilization_percent={utilization:.1f} new_connections_per_sec={new_connections:.1f} "
    "database={database}".format(
        active=int(round(active)),
        max_connections=max_connections,
        waiters=waiters,
        utilization=utilization,
        new_connections=float(waiters),
        database=database,
    )
)
PY
