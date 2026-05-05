#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${1:?namespace is required}"
CONFIGMAP="${2:?configmap is required}"
KEY="${3:?data key is required}"

command -v kubectl >/dev/null 2>&1 || { echo "kubectl is required" >&2; exit 127; }
command -v python3 >/dev/null 2>&1 || { echo "python3 is required" >&2; exit 127; }

kubectl -n "$NAMESPACE" get configmap "$CONFIGMAP" -o json | python3 - "$KEY" <<'PY'
import json
import sys

key = sys.argv[1]
payload = json.load(sys.stdin)
sys.stdout.write(payload.get("data", {}).get(key, ""))
PY
