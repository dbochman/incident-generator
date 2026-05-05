#!/usr/bin/env bash
set -euo pipefail

NAMESPACE="${1:?namespace is required}"
CONFIGMAP="${2:?configmap is required}"
KEY="${3:?data key is required}"

command -v kubectl >/dev/null 2>&1 || { echo "kubectl is required" >&2; exit 127; }
command -v python3 >/dev/null 2>&1 || { echo "python3 is required" >&2; exit 127; }

tmp="$(mktemp)"
cleanup() {
  rm -f "$tmp"
}
trap cleanup EXIT

kubectl -n "$NAMESPACE" get configmap "$CONFIGMAP" -o json > "$tmp"
python3 - "$KEY" "$tmp" <<'PY'
import json
import sys

key = sys.argv[1]
path = sys.argv[2]
with open(path, encoding="utf-8") as fh:
    payload = json.load(fh)
sys.stdout.write(payload.get("data", {}).get(key, ""))
PY
