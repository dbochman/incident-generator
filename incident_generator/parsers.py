"""Raw command output parsers used by evidence adapters."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml


REDACTION_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key=)[^\s]+"),
    re.compile(r"(?i)(aws[_-]?key=)AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)(token=)[^\s]+"),
    re.compile(r"(?i)(password=)[^\s]+"),
    re.compile(r"(?i)(secret=)[^\s]+"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
]


def load_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle)
    if not isinstance(loaded, dict):
        raise ValueError(f"Expected YAML mapping in {path}")
    return loaded


def load_fixture_outputs(fixture_dir: Path) -> dict[str, str]:
    outputs_dir = fixture_dir / "outputs"
    if not outputs_dir.is_dir():
        raise FileNotFoundError(f"Missing fixture outputs directory: {outputs_dir}")

    outputs = {}
    for path in outputs_dir.glob("*.txt"):
        outputs[path.stem] = load_text(path)
    return outputs


def redact(text: str) -> str:
    redacted = text
    for pattern in REDACTION_PATTERNS:
        if pattern.pattern.startswith("(?i)(aws"):
            redacted = pattern.sub(r"\1[REDACTED_AWS_ACCESS_KEY]", redacted)
        elif pattern.pattern.startswith("AKIA"):
            redacted = pattern.sub("[REDACTED_AWS_ACCESS_KEY]", redacted)
        else:
            redacted = pattern.sub(r"\1[REDACTED]", redacted)
    return redacted


def parse_pod_summary(output: str) -> dict[str, Any]:
    lines = [line for line in output.splitlines() if line.strip()]
    if len(lines) < 2:
        return {}

    headers = re.split(r"\s{2,}|\t+", lines[0].strip())
    values = re.split(r"\s{2,}|\t+", lines[1].strip())
    row = dict(zip(headers, values))
    restarts = row.get("RESTARTS", "0")

    restart_match = re.search(r"\d+", restarts)
    return {
        "pod": row.get("NAME"),
        "ready": row.get("READY", ""),
        "status": row.get("STATUS"),
        "restart_count": int(restart_match.group(0)) if restart_match else 0,
        "age": row.get("AGE"),
        "ip": row.get("IP"),
        "node": row.get("NODE"),
    }


def parse_describe(output: str) -> dict[str, Any]:
    evidence: dict[str, Any] = {
        "termination_reason": None,
        "exit_code": None,
        "state": None,
        "last_state": None,
        "events": [],
    }

    in_last_state = False
    in_events = False
    for raw_line in output.splitlines():
        stripped = raw_line.rstrip().strip()

        if stripped.startswith("State:"):
            evidence["state"] = stripped.split(":", 1)[1].strip()
            in_last_state = False
            continue
        if stripped.startswith("Last State:"):
            evidence["last_state"] = stripped.split(":", 1)[1].strip()
            in_last_state = True
            continue
        if in_last_state and stripped.startswith("Reason:"):
            evidence["termination_reason"] = stripped.split(":", 1)[1].strip()
            continue
        if in_last_state and stripped.startswith("Exit Code:"):
            exit_value = stripped.split(":", 1)[1].strip()
            evidence["exit_code"] = int(exit_value) if exit_value.isdigit() else exit_value
            continue
        if stripped.startswith("Events:"):
            in_events = True
            continue
        if in_events and stripped and not stripped.startswith(("Type", "----")):
            evidence["events"].append(stripped)

    return evidence


def parse_logs(output: str) -> dict[str, Any]:
    safe_output = redact(output)
    lower = safe_output.lower()
    signals = []
    for needle in [
        "out of memory",
        "oom",
        "panic",
        "fatal",
        "missing",
        "permission denied",
        "connection refused",
        "timeout",
        "no such host",
        "segmentation fault",
    ]:
        if needle in lower:
            signals.append(needle)

    interesting_lines = [
        line.strip()
        for line in safe_output.splitlines()
        if any(token in line.lower() for token in signals)
    ]
    return {
        "signals": signals,
        "interesting_lines": interesting_lines[:10],
    }


def percent_to_int(value: str | None) -> int | None:
    if not value:
        return None
    match = re.search(r"\d+", value)
    return int(match.group(0)) if match else None


def parse_df(output: str) -> dict[str, Any]:
    lines = [line for line in output.splitlines() if line.strip()]
    if len(lines) < 2:
        return {}

    headers = re.split(r"\s+", lines[0].strip())
    values = re.split(r"\s+", lines[1].strip())
    row = dict(zip(headers, values))
    return {
        "filesystem": row.get("Filesystem"),
        "size": row.get("Size") or row.get("1024-blocks") or row.get("1K-blocks"),
        "used": row.get("Used"),
        "available": row.get("Avail") or row.get("Available"),
        "use_percent": percent_to_int(row.get("Use%") or row.get("IUse%") or row.get("Capacity")),
        "mounted_on": row.get("Mounted"),
    }


def parse_du(output: str) -> list[dict[str, str]]:
    entries = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parts = re.split(r"\s+", stripped, maxsplit=1)
        if len(parts) == 2:
            entries.append({"size": parts[0], "path": parts[1]})
    return entries


def parse_lsof_deleted(output: str) -> dict[str, Any]:
    lines = [
        line.strip()
        for line in output.splitlines()
        if "(deleted)" in line.lower()
    ]
    return {
        "count": len(lines),
        "entries": lines[:10],
    }


def parse_uptime(output: str) -> dict[str, Any]:
    match = re.search(r"load average[s]?:\s*([0-9.]+),\s*([0-9.]+),\s*([0-9.]+)", output)
    if not match:
        return {}
    return {
        "load_1m": float(match.group(1)),
        "load_5m": float(match.group(2)),
        "load_15m": float(match.group(3)),
    }


def parse_cpu_line(output: str) -> dict[str, Any]:
    match = re.search(r"([0-9.]+)\s*id", output)
    if match:
        idle = float(match.group(1))
    else:
        idle = _parse_mpstat_idle(output)
        if idle is None:
            return {}
    return {
        "idle_percent": idle,
        "used_percent": round(100.0 - idle, 1),
    }


def parse_top_processes(output: str) -> list[dict[str, Any]]:
    lines = [line for line in output.splitlines() if line.strip()]
    if len(lines) < 2:
        return []

    headers = re.split(r"\s+", lines[0].strip())
    entries = []
    for line in lines[1:]:
        parts = re.split(r"\s+", line.strip())
        parsed = _parse_ps_cpu_row(headers, parts)
        if parsed is None:
            continue
        entries.append(parsed)
    return entries


def _parse_mpstat_idle(output: str) -> float | None:
    for line in reversed([line.strip() for line in output.splitlines() if line.strip()]):
        parts = re.split(r"\s+", line)
        if len(parts) >= 3 and parts[0].startswith("Average:") and parts[1] == "all":
            try:
                return float(parts[-1])
            except ValueError:
                return None
    return None


def _parse_ps_cpu_row(headers: list[str], parts: list[str]) -> dict[str, Any] | None:
    try:
        pid_idx = headers.index("PID")
        user_idx = headers.index("USER")
        cpu_idx = headers.index("%CPU")
        mem_idx = headers.index("%MEM")
        command_idx = headers.index("COMMAND")
    except ValueError:
        return None
    if len(parts) <= max(pid_idx, user_idx, cpu_idx, mem_idx, command_idx):
        return None
    try:
        cpu_percent = float(parts[cpu_idx])
        mem_percent = float(parts[mem_idx])
    except ValueError:
        return None
    return {
        "pid": parts[pid_idx],
        "user": parts[user_idx],
        "cpu_percent": cpu_percent,
        "mem_percent": mem_percent,
        "command": " ".join(parts[command_idx:]),
    }


def parse_free(output: str) -> dict[str, Any]:
    lines = [line for line in output.splitlines() if line.strip()]
    mem_line = next((line for line in lines if line.startswith("Mem:")), "")
    swap_line = next((line for line in lines if line.startswith("Swap:")), "")
    if not mem_line:
        return {}

    mem_parts = re.split(r"\s+", mem_line.strip())
    swap_parts = re.split(r"\s+", swap_line.strip()) if swap_line else []
    if len(mem_parts) < 7:
        return {}

    total = int(mem_parts[1])
    used = int(mem_parts[2])
    available = int(mem_parts[6])
    swap_total = int(swap_parts[1]) if len(swap_parts) > 2 else 0
    swap_used = int(swap_parts[2]) if len(swap_parts) > 2 else 0
    return {
        "total_mib": total,
        "used_mib": used,
        "available_mib": available,
        "used_percent": round((used / total) * 100, 1) if total else 0,
        "available_percent": round((available / total) * 100, 1) if total else 0,
        "swap_total_mib": swap_total,
        "swap_used_mib": swap_used,
    }


def parse_top_memory_processes(output: str) -> list[dict[str, Any]]:
    lines = [line for line in output.splitlines() if line.strip()]
    if len(lines) < 2:
        return []

    headers = re.split(r"\s+", lines[0].strip())
    entries = []
    for line in lines[1:]:
        parts = re.split(r"\s+", line.strip())
        parsed = _parse_ps_memory_row(headers, parts)
        if parsed is None:
            continue
        entries.append(parsed)
    return entries


def _parse_ps_memory_row(headers: list[str], parts: list[str]) -> dict[str, Any] | None:
    try:
        pid_idx = headers.index("PID")
        user_idx = headers.index("USER")
        rss_idx = headers.index("RSS")
        cpu_idx = headers.index("%CPU")
        mem_idx = headers.index("%MEM")
        command_idx = headers.index("COMMAND")
    except ValueError:
        return None
    if len(parts) <= max(pid_idx, user_idx, rss_idx, cpu_idx, mem_idx, command_idx):
        return None
    try:
        rss_kib = int(parts[rss_idx])
        cpu_percent = float(parts[cpu_idx])
        mem_percent = float(parts[mem_idx])
    except ValueError:
        return None
    return {
        "pid": parts[pid_idx],
        "user": parts[user_idx],
        "rss_kib": rss_kib,
        "cpu_percent": cpu_percent,
        "mem_percent": mem_percent,
        "command": " ".join(parts[command_idx:]),
    }


def parse_oom_events(output: str) -> dict[str, Any]:
    safe_output = redact(output)
    lines = [
        line.strip()
        for line in safe_output.splitlines()
        if "out of memory" in line.lower() or "oom-kill" in line.lower() or "killed process" in line.lower()
    ]
    return {
        "count": len(lines),
        "entries": lines[:10],
    }


def parse_endpoint_check(output: str) -> dict[str, Any]:
    safe_output = redact(output)
    status_match = re.search(r"(?:HTTP/\S+\s+|status=)(\d{3})", safe_output)
    latency_match = re.search(r"(?:time_total=|latency_ms=)([0-9.]+)", safe_output)
    return {
        "status_code": int(status_match.group(1)) if status_match else None,
        "latency_ms": float(latency_match.group(1)) if latency_match else None,
        "raw": safe_output.strip(),
    }


def parse_error_logs(output: str) -> dict[str, Any]:
    safe_output = redact(output)
    signals = []
    for needle in [
        "500",
        "502",
        "503",
        "exception",
        "panic",
        "timeout",
        "connection refused",
        "database",
        "redis",
        "upstream",
        "too many connections",
        "pool exhausted",
        "consumer lag",
        "rebalance",
        "heartbeat timeout",
        "consumer unavailable",
        "poison",
        "deserialization",
    ]:
        if needle in safe_output.lower():
            signals.append(needle)
    lines = [
        line.strip()
        for line in safe_output.splitlines()
        if any(signal in line.lower() for signal in signals)
    ]
    return {
        "signals": signals,
        "entries": lines[:10],
    }


def parse_structured_log_signatures(output: str) -> dict[str, Any]:
    safe_output = redact(output)
    if not safe_output.strip():
        return {}

    signatures = []
    routes = []
    versions = []
    samples = []
    fields: dict[str, Any] = {}
    for line in safe_output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parsed = _parse_key_value_fields(stripped)
        if stripped.startswith("signature="):
            signatures.append(parsed or {"raw": stripped})
        elif stripped.startswith("route="):
            routes.append(parsed or {"raw": stripped})
        elif stripped.startswith("version="):
            versions.append(parsed or {"raw": stripped})
        elif stripped.startswith("sample"):
            samples.append(parsed or {"raw": stripped})
        else:
            fields.update(parsed)

    fields["signature_count"] = len(signatures)
    fields["dominant_signature"] = signatures[0] if signatures else {}
    fields["signatures"] = signatures[:20]
    fields["routes"] = routes[:20]
    fields["versions"] = versions[:20]
    fields["samples"] = samples[:10]
    fields.setdefault("raw", safe_output.strip())
    return fields


def parse_recent_deploys(output: str) -> dict[str, Any]:
    annotation_text = _deployment_annotation_text(output, "sre-agent.io/recent-deploys")
    safe_output = redact(annotation_text if annotation_text is not None else output)
    deploys = []
    for line in safe_output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        fields = {}
        for part in re.split(r"\s+", stripped):
            if "=" in part:
                key, value = part.split("=", 1)
                fields[key] = value
        if fields:
            if "minutes_ago" in fields:
                fields["minutes_ago"] = int(fields["minutes_ago"])
            deploys.append(fields)
    return {
        "count": len(deploys),
        "latest": deploys[0] if deploys else {},
        "entries": deploys[:10],
    }


def parse_deploy_metadata(output: str) -> dict[str, Any]:
    annotation_text = _deployment_annotation_text(output, "sre-agent.io/deploy-metadata")
    safe_output = redact(annotation_text if annotation_text is not None else output)
    fields: dict[str, Any] = {}
    changes = []
    annotations = []

    for line in safe_output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parsed = _parse_key_value_fields(stripped)
        if stripped.startswith("change"):
            changes.append(parsed or {"raw": stripped})
        elif stripped.startswith("annotation"):
            annotations.append(parsed or {"raw": stripped})
        else:
            fields.update(parsed)

    fields["changes"] = changes[:20]
    fields["annotations"] = annotations[:20]
    fields.setdefault("raw", safe_output.strip())
    return fields


def _deployment_annotation_text(output: str, key: str) -> str | None:
    stripped = output.strip()
    if not stripped.startswith("{"):
        return None
    try:
        loaded = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if not isinstance(loaded, dict):
        return None
    metadata = loaded.get("metadata") or {}
    if not isinstance(metadata, dict):
        return None
    annotations = metadata.get("annotations") or {}
    if not isinstance(annotations, dict):
        return None
    value = annotations.get(key)
    return value if isinstance(value, str) else None


def parse_incident_timeline(output: str) -> dict[str, Any]:
    safe_output = redact(output)
    if not safe_output.strip():
        return {}

    fields: dict[str, Any] = {}
    events = []
    for line in safe_output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parsed = _parse_key_value_fields(stripped)
        if stripped.startswith("event="):
            events.append(parsed or {"raw": stripped})
        else:
            fields.update(parsed)

    fields["events"] = events[:20]
    fields.setdefault("raw", safe_output.strip())
    return fields


def parse_pagerduty_escalation(output: str) -> dict[str, Any]:
    safe_output = redact(output)
    if not safe_output.strip():
        return {}

    fields: dict[str, Any] = {}
    on_call = []
    escalations = []
    events = []
    for line in safe_output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parsed = _parse_key_value_fields(stripped)
        if stripped.startswith("on_call"):
            on_call.append(parsed or {"raw": stripped})
        elif stripped.startswith("escalation"):
            escalations.append(parsed or {"raw": stripped})
        elif stripped.startswith("event="):
            events.append(parsed or {"raw": stripped})
        else:
            fields.update(parsed)

    assigned_to = fields.get("assigned_to")
    if isinstance(assigned_to, str):
        fields["assigned_to"] = [
            assignee
            for assignee in assigned_to.split(",")
            if assignee and assignee.lower() not in {"none", "n/a"}
        ]
    fields["on_call"] = on_call[:20]
    fields["escalations"] = escalations[:20]
    fields["events"] = events[:20]
    fields.setdefault("raw", safe_output.strip())
    return fields


def parse_slo_status(output: str) -> dict[str, Any]:
    safe_output = redact(output)
    if not safe_output.strip():
        return {}

    fields: dict[str, Any] = {}
    routes = []
    events = []
    for line in safe_output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parsed = _coerce_boolean_fields(_parse_key_value_fields(stripped))
        if stripped.startswith("route="):
            routes.append(parsed or {"raw": stripped})
        elif stripped.startswith("event="):
            events.append(parsed or {"raw": stripped})
        else:
            fields.update(parsed)

    fields["routes"] = routes[:20]
    fields["events"] = events[:20]
    fields.setdefault("raw", safe_output.strip())
    return fields


def parse_saturation_metrics(output: str) -> dict[str, Any]:
    safe_output = redact(output)
    if not safe_output.strip():
        return {}

    fields: dict[str, Any] = {}
    pods = []
    dependencies = []
    routes = []
    events = []
    for line in safe_output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parsed = _parse_key_value_fields(stripped)
        if stripped.startswith("pod="):
            pods.append(parsed or {"raw": stripped})
        elif stripped.startswith("dependency="):
            dependencies.append(parsed or {"raw": stripped})
        elif stripped.startswith("route="):
            routes.append(parsed or {"raw": stripped})
        elif stripped.startswith("event="):
            events.append(parsed or {"raw": stripped})
        else:
            fields.update(parsed)

    fields["pods"] = pods[:20]
    fields["dependencies"] = dependencies[:20]
    fields["routes"] = routes[:20]
    fields["events"] = events[:20]
    fields.setdefault("raw", safe_output.strip())
    return fields


def parse_trace_summary(output: str) -> dict[str, Any]:
    safe_output = redact(output)
    spans = []
    for line in safe_output.splitlines():
        fields = {}
        for part in re.split(r"\s+", line.strip()):
            if "=" in part:
                key, value = part.split("=", 1)
                fields[key] = value
        if fields:
            if "duration_ms" in fields:
                fields["duration_ms"] = float(fields["duration_ms"])
            spans.append(fields)
    return {
        "count": len(spans),
        "slowest": spans[0] if spans else {},
        "entries": spans[:10],
    }


def parse_span_attributes(output: str) -> dict[str, Any]:
    safe_output = redact(output)
    entries = []
    merged: dict[str, Any] = {}
    for line in safe_output.splitlines():
        fields = _parse_key_value_fields(line)
        if not fields:
            continue
        entries.append(fields)
        for key, value in fields.items():
            merged.setdefault(key, value)

    return {
        "count": len(entries),
        "attributes": merged,
        "entries": entries[:20],
        "raw": safe_output.strip(),
    }


def parse_dns_lookup(output: str) -> dict[str, Any]:
    safe_output = redact(output)
    lower = safe_output.lower()
    records = []
    errors = []
    status = "unknown"

    for line in safe_output.splitlines():
        stripped = line.strip()
        line_lower = stripped.lower()
        if not stripped:
            continue
        if re.search(r"\s+IN\s+(A|AAAA|CNAME)\s+", stripped):
            records.append(stripped)
        if any(token in line_lower for token in ["nxdomain", "servfail", "no such host", "timeout"]):
            errors.append(stripped)

    if "nxdomain" in lower or "no such host" in lower:
        status = "nxdomain"
    elif "servfail" in lower:
        status = "servfail"
    elif "timeout" in lower:
        status = "timeout"
    elif records:
        status = "resolved"

    return {
        "status": status,
        "record_count": len(records),
        "records": records[:10],
        "errors": errors[:10],
        "raw": safe_output.strip(),
    }


def parse_tls_check(output: str) -> dict[str, Any]:
    safe_output = redact(output)
    fields = {}
    for part in re.split(r"\s+", safe_output.strip()):
        if "=" in part:
            key, value = part.split("=", 1)
            fields[key] = value

    days_remaining = fields.get("days_remaining")
    if days_remaining is not None:
        fields["days_remaining"] = int(days_remaining)

    if "valid" in fields:
        fields["valid"] = fields["valid"].lower() in ["true", "yes", "1"]
    if "hostname_match" in fields:
        fields["hostname_match"] = fields["hostname_match"].lower() in ["true", "yes", "1"]

    fields.setdefault("raw", safe_output.strip())
    return fields


def parse_db_pool(output: str) -> dict[str, Any]:
    safe_output = redact(output)
    fields = _parse_key_value_fields(safe_output)
    fields.setdefault("raw", safe_output.strip())
    return fields


def parse_queue_consumer_lag(output: str) -> dict[str, Any]:
    safe_output = redact(output)
    fields: dict[str, Any] = {}
    partitions = []

    for line in safe_output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parsed = _parse_key_value_fields(stripped)
        if stripped.startswith("partition="):
            partitions.append(parsed)
            continue
        fields.update(parsed)

    if "total_lag" not in fields and partitions:
        fields["total_lag"] = sum(int(partition.get("lag", 0)) for partition in partitions)
    if "max_partition_lag" not in fields and partitions:
        fields["max_partition_lag"] = max(int(partition.get("lag", 0)) for partition in partitions)

    fields["partition_lags"] = partitions[:20]
    fields.setdefault("raw", safe_output.strip())
    return fields


def parse_kafka_group_state(output: str) -> dict[str, Any]:
    safe_output = redact(output)
    fields: dict[str, Any] = {}
    members = []
    events = []

    for line in safe_output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parsed = _parse_key_value_fields(stripped)
        if stripped.startswith("member="):
            members.append(parsed)
        elif stripped.startswith("event="):
            events.append(parsed or {"raw": stripped})
        else:
            fields.update(parsed)

    if "members" not in fields and members:
        fields["members"] = len(members)
    fields["member_details"] = members[:20]
    fields["events"] = events[:20]
    fields.setdefault("raw", safe_output.strip())
    return fields


def parse_queue_dead_letter(output: str) -> dict[str, Any]:
    safe_output = redact(output)
    fields: dict[str, Any] = {}
    samples = []

    for line in safe_output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        parsed = _parse_key_value_fields(stripped)
        if not fields:
            fields.update(parsed)
        elif stripped.startswith("sample") or "error=" in stripped:
            samples.append(stripped)

    lower = safe_output.lower()
    signals = [
        needle
        for needle in [
            "poison",
            "deserialization",
            "schema",
            "invalid json",
            "timeout",
            "retry exhausted",
        ]
        if needle in lower
    ]

    fields["signals"] = signals
    fields["samples"] = samples[:10]
    fields.setdefault("raw", safe_output.strip())
    return fields


def parse_ping_summary(output: str) -> dict[str, Any]:
    safe_output = redact(output)
    packet_match = re.search(r"([0-9.]+)%\s+packet loss", safe_output)
    rtt_match = re.search(r"(?:round-trip|rtt).*=\s*([0-9.]+)/([0-9.]+)/([0-9.]+)/([0-9.]+)", safe_output)
    return {
        "packet_loss_percent": float(packet_match.group(1)) if packet_match else None,
        "rtt_min_ms": float(rtt_match.group(1)) if rtt_match else None,
        "rtt_avg_ms": float(rtt_match.group(2)) if rtt_match else None,
        "rtt_max_ms": float(rtt_match.group(3)) if rtt_match else None,
        "raw": safe_output.strip(),
    }


def parse_mtr_summary(output: str) -> dict[str, Any]:
    safe_output = redact(output)
    hops = []
    for line in safe_output.splitlines():
        stripped = line.strip()
        if not re.match(r"\d+\.", stripped):
            continue
        parts = re.split(r"\s+", stripped)
        if len(parts) < 8:
            continue
        try:
            hops.append(
                {
                    "hop": parts[0].rstrip("."),
                    "host": parts[1],
                    "loss_percent": float(parts[2].rstrip("%")),
                    "avg_ms": float(parts[5]),
                    "worst_ms": float(parts[7]),
                    "raw": stripped,
                }
            )
        except ValueError:
            continue

    worst_loss = max(hops, key=lambda item: item["loss_percent"]) if hops else {}
    worst_latency = max(hops, key=lambda item: item["avg_ms"]) if hops else {}
    return {
        "count": len(hops),
        "worst_loss": worst_loss,
        "worst_latency": worst_latency,
        "hops": hops[:10],
        "raw": safe_output.strip(),
    }


def parse_node_conditions(output: str) -> dict[str, Any]:
    safe_output = redact(output)
    conditions = {}
    events = []
    for line in safe_output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        fields = {}
        for part in re.split(r"\s+", stripped):
            if "=" in part:
                key, value = part.split("=", 1)
                fields[key] = value
        if fields.get("type"):
            conditions[fields["type"]] = fields.get("status")
        else:
            events.append(stripped)
    return {
        "conditions": conditions,
        "events": events[:10],
        "raw": safe_output.strip(),
    }


def _parse_key_value_fields(text: str) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for part in re.split(r"\s+", text.strip()):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        if re.fullmatch(r"-?\d+", value):
            fields[key] = int(value)
        elif re.fullmatch(r"-?\d+\.\d+", value):
            fields[key] = float(value)
        else:
            fields[key] = value
    return fields


def _coerce_boolean_fields(fields: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value.lower() == "true" if isinstance(value, str) and value.lower() in {"true", "false"} else value
        for key, value in fields.items()
    }
