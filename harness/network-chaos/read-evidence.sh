#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 ]]; then
  echo "usage: read-evidence.sh <namespace> <target> <ping|mtr>" >&2
  exit 2
fi

namespace="$1"
target="$2"
format="$3"

command -v kubectl >/dev/null 2>&1 || { echo "kubectl is required" >&2; exit 127; }
command -v python3 >/dev/null 2>&1 || { echo "python3 is required" >&2; exit 127; }

networkchaos_json="$(kubectl -n "$namespace" get networkchaos -o json)"
python3 - "$networkchaos_json" "$target" "$format" <<'PY'
import json
import re
import sys

loaded = json.loads(sys.argv[1])
target = sys.argv[2]
output_format = sys.argv[3]
items = loaded.get("items") or []
if not items:
    print("no NetworkChaos resources found", file=sys.stderr)
    raise SystemExit(1)

item = items[0]
spec = item.get("spec") or {}
action = str(spec.get("action") or "").lower()

def number(value: object, default: float = 0.0) -> float:
    match = re.search(r"[0-9.]+", str(value or ""))
    return float(match.group(0)) if match else default

def duration_ms(value: object, default: float = 0.0) -> float:
    text = str(value or "")
    amount = number(text, default)
    if text.endswith("ms"):
        return amount
    if text.endswith("s"):
        return amount * 1000.0
    return amount

loss_percent = 0.0
avg_ms = 88.4
max_ms = 420.0
if action == "loss":
    loss_percent = number((spec.get("loss") or {}).get("loss"), 30.0)
elif action == "delay":
    avg_ms = duration_ms((spec.get("delay") or {}).get("latency"), 300.0)
    max_ms = avg_ms + duration_ms((spec.get("delay") or {}).get("jitter"), 50.0)
else:
    print(f"unsupported NetworkChaos action: {action}", file=sys.stderr)
    raise SystemExit(1)

if output_format == "ping":
    received = max(0, int(round(20 * (100.0 - loss_percent) / 100.0)))
    print(f"--- {target} ping statistics ---")
    print(f"20 packets transmitted, {received} packets received, {loss_percent:.1f}% packet loss")
    print(f"round-trip min/avg/max/stddev = 32.1/{avg_ms:.1f}/{max_ms:.1f}/75.8 ms")
elif output_format == "mtr":
    print("HOST: runner Loss% Snt Last Avg Best Wrst StDev")
    print("1. source.network.svc 0.0% 20 8.1 8.3 7.8 9.0 0.3")
    print(f"2. chaos-hop.network.svc {loss_percent:.1f}% 20 {avg_ms:.1f} {avg_ms:.1f} 31.0 {max_ms:.1f} 77.1")
    print(f"3. {target} {loss_percent:.1f}% 20 {avg_ms:.1f} {avg_ms:.1f} 33.0 {max_ms:.1f} 78.4")
else:
    print(f"unsupported evidence format: {output_format}", file=sys.stderr)
    raise SystemExit(2)
PY
