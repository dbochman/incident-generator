#!/usr/bin/env python3
"""Emit parser-compatible Kubernetes node condition evidence."""

from __future__ import annotations

import json
import subprocess
import sys


def _kubectl_json(args: list[str]) -> dict:
    completed = subprocess.run(["kubectl", *args, "-o", "json"], capture_output=True, check=False, text=True)
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        raise SystemExit(stderr or f"kubectl {' '.join(args)} failed")
    return json.loads(completed.stdout or "{}")


def main() -> int:
    if len(sys.argv) != 2 or not sys.argv[1]:
        print("usage: read-evidence.py <node>", file=sys.stderr)
        return 2
    node = sys.argv[1]
    node_json = _kubectl_json(["get", "node", node])
    for condition in node_json.get("status", {}).get("conditions", []):
        condition_type = condition.get("type")
        status = condition.get("status")
        if not condition_type:
            continue
        reason = str(condition.get("reason") or "").replace(" ", "_")
        message = str(condition.get("message") or "").replace("\n", " ")
        print(f"type={condition_type} status={status} reason={reason} message={message}")

    events = _kubectl_json(
        [
            "get",
            "events",
            "--all-namespaces",
            "--field-selector",
            f"involvedObject.kind=Node,involvedObject.name={node}",
        ]
    )
    for item in events.get("items", [])[:10]:
        reason = item.get("reason") or "-"
        message = str(item.get("message") or "").replace("\n", " ")
        event_type = item.get("type") or "Normal"
        print(f"{event_type} {reason} {message}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
