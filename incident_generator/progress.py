"""Operator progress reporting for incident generation runs."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, TextIO

from .benchmark_result_helpers import write_json_file as _write_json_file


PROGRESS_SCHEMA_VERSION = "incident-generator.progress/v1"
PROGRESS_DASHBOARD_SCHEMA_VERSION = "incident-generator.progress-dashboard/v1"


@dataclass(frozen=True)
class ProgressEvent:
    phase: str
    status: str
    message: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""
    elapsed_ms: int = 0

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "schema_version": PROGRESS_SCHEMA_VERSION,
            "timestamp": self.timestamp,
            "elapsed_ms": self.elapsed_ms,
            "phase": self.phase,
            "status": self.status,
            "message": self.message,
            "details": self.details,
        }
        return payload


class NoopProgressReporter:
    artifact_dir: Path | None = None
    events_path: Path | None = None
    summary_path: Path | None = None
    dashboard_path: Path | None = None
    dashboard_markdown_path: Path | None = None

    def emit(
        self,
        phase: str,
        status: str,
        message: str = "",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        del phase, status, message, details

    def write_summary(self, result: dict[str, Any]) -> None:
        del result

    def close(self) -> None:
        return None


class OperatorProgressReporter:
    """Write progress events to an optional stream and artifact directory."""

    def __init__(
        self,
        *,
        stream: TextIO | None = None,
        stream_format: str | None = "human",
        artifact_dir: Path | None = None,
        clock: Any = time.monotonic,
    ) -> None:
        if stream_format not in {None, "human", "ndjson"}:
            raise ValueError("stream_format must be one of None, 'human', or 'ndjson'")
        self.stream = stream
        self.stream_format = stream_format
        self.artifact_dir = artifact_dir
        self.events_path = artifact_dir / "events.ndjson" if artifact_dir is not None else None
        self.summary_path = artifact_dir / "summary.json" if artifact_dir is not None else None
        self.dashboard_path = artifact_dir / "dashboard.json" if artifact_dir is not None else None
        self.dashboard_markdown_path = artifact_dir / "dashboard.md" if artifact_dir is not None else None
        self._clock = clock
        self._started = float(clock())
        self._events: list[dict[str, Any]] = []
        self._events_file: TextIO | None = None
        if artifact_dir is not None:
            artifact_dir.mkdir(parents=True, exist_ok=True)
            self._events_file = self.events_path.open("w", encoding="utf-8")

    def emit(
        self,
        phase: str,
        status: str,
        message: str = "",
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        event = ProgressEvent(
            phase=phase,
            status=status,
            message=message,
            details=_jsonable(details or {}),
            timestamp=_utc_timestamp(),
            elapsed_ms=max(0, int((float(self._clock()) - self._started) * 1000)),
        )
        payload = event.to_dict()
        self._events.append(payload)
        if self.stream is not None and self.stream_format is not None:
            self._write_stream(payload)
        if self._events_file is not None:
            self._events_file.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
            self._events_file.flush()
        self._write_dashboard()

    def write_summary(self, result: dict[str, Any]) -> None:
        if self.summary_path is None:
            return
        _write_json_file(self.summary_path, _jsonable(result))
        self._write_dashboard(result)

    def close(self) -> None:
        if self._events_file is not None:
            self._events_file.close()
            self._events_file = None

    def _write_stream(self, payload: dict[str, Any]) -> None:
        assert self.stream is not None
        if self.stream_format == "ndjson":
            self.stream.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
        else:
            self.stream.write(_human_line(payload) + "\n")
        self.stream.flush()

    def _write_dashboard(self, result: dict[str, Any] | None = None) -> None:
        if self.dashboard_path is None or self.dashboard_markdown_path is None:
            return
        dashboard = build_progress_dashboard(self._events, result=result)
        _write_json_file(self.dashboard_path, dashboard)
        self.dashboard_markdown_path.write_text(render_progress_dashboard_markdown(dashboard), encoding="utf-8")


def default_artifact_dir(root: Path, incident_session_id: str) -> Path:
    return root / ".tmp" / "incidents" / _slug(incident_session_id or "incident-generator-run")


def progress_artifacts(reporter: Any) -> dict[str, str]:
    artifact_dir = getattr(reporter, "artifact_dir", None)
    events_path = getattr(reporter, "events_path", None)
    summary_path = getattr(reporter, "summary_path", None)
    dashboard_path = getattr(reporter, "dashboard_path", None)
    dashboard_markdown_path = getattr(reporter, "dashboard_markdown_path", None)
    artifacts: dict[str, str] = {}
    if artifact_dir is not None:
        artifacts["directory"] = str(artifact_dir)
    if events_path is not None:
        artifacts["events"] = str(events_path)
    if summary_path is not None:
        artifacts["summary"] = str(summary_path)
    if dashboard_path is not None:
        artifacts["dashboard"] = str(dashboard_path)
    if dashboard_markdown_path is not None:
        artifacts["dashboard_markdown"] = str(dashboard_markdown_path)
    return artifacts


def build_progress_dashboard(
    events: Iterable[dict[str, Any]],
    *,
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    event_list = [_jsonable(event) for event in events]
    status = _dashboard_status(event_list, result)
    return {
        "schema_version": PROGRESS_DASHBOARD_SCHEMA_VERSION,
        "status": status,
        "failure_class": result.get("failure_class") if isinstance(result, dict) else None,
        "failure_classification": result.get("failure_classification") if isinstance(result, dict) else None,
        "updated_at": _utc_timestamp(),
        "elapsed_ms": _last_elapsed_ms(event_list),
        "phase_timings": _phase_timings(event_list),
        "runtime_state": _runtime_state(event_list),
        "live_look": _live_look(event_list, result),
        "seed_checkpoints": _seed_checkpoints(event_list),
        "wait_predicates": _wait_predicates(event_list),
        "teardown": _teardown_status(event_list, result),
    }


def render_progress_dashboard_markdown(dashboard: dict[str, Any]) -> str:
    lines = [
        "# Incident Generator Progress Dashboard",
        "",
        f"Status: `{dashboard.get('status', 'unknown')}`",
        f"Failure class: `{dashboard.get('failure_class') or 'none'}`",
        f"Elapsed: `{_format_elapsed(int(dashboard.get('elapsed_ms') or 0))}`",
        "",
        "## Phase Timing",
        "",
        "| Phase | Status | Events | First | Last | Duration | Last message |",
        "| --- | --- | ---: | --- | --- | --- | --- |",
    ]
    for phase in dashboard.get("phase_timings", []):
        lines.append(
            "| {phase} | {status} | {events} | {first} | {last} | {duration} | {message} |".format(
                phase=_md_code(phase.get("phase")),
                status=_md_code(phase.get("status")),
                events=int(phase.get("event_count") or 0),
                first=_md_code(_format_elapsed(int(phase.get("first_elapsed_ms") or 0))),
                last=_md_code(_format_elapsed(int(phase.get("last_elapsed_ms") or 0))),
                duration=_md_code(_format_elapsed(int(phase.get("duration_ms") or 0))),
                message=_md_text(phase.get("last_message") or "-"),
            )
        )
    runtime = dashboard.get("runtime_state") if isinstance(dashboard.get("runtime_state"), dict) else {}
    lines.extend(["", "## Runtime State", ""])
    if runtime:
        for key in ("archetype", "cluster", "compose_project", "docker_host", "kubeconfig_path"):
            if runtime.get(key):
                lines.append(f"- {key}: `{runtime[key]}`")
    else:
        lines.append("- No runtime state observed yet.")
    live_look = dashboard.get("live_look") if isinstance(dashboard.get("live_look"), dict) else {}
    lines.extend(["", "## Live Look", ""])
    if live_look.get("headline"):
        lines.append(str(live_look["headline"]))
        lines.append("")
    lines.extend(["### System Health Signals", ""])
    lines.extend(_markdown_rows(live_look.get("system_health"), ("elapsed", "source", "signal", "status", "detail")))
    lines.extend(["", "### Recent Timeline", ""])
    lines.extend(_markdown_rows(live_look.get("timeline"), ("elapsed", "phase", "status", "message", "detail")))
    lines.extend(["", "### Containers", ""])
    lines.extend(_markdown_rows(runtime.get("containers"), ("name", "image", "status")))
    lines.extend(["", "### Images", ""])
    lines.extend(_markdown_rows(runtime.get("images"), ("repository", "id", "size")))
    lines.extend(["", "## Seed Checkpoints", ""])
    lines.extend(_markdown_rows(dashboard.get("seed_checkpoints"), ("scenario", "status", "applied", "elapsed")))
    lines.extend(["", "## Wait Predicates", ""])
    lines.extend(_markdown_rows(dashboard.get("wait_predicates"), ("scenario", "kind", "status", "matched", "observed")))
    lines.extend(["", "## Teardown", ""])
    lines.extend(_markdown_rows(dashboard.get("teardown"), ("phase", "step", "scenario", "status", "failures")))
    return "\n".join(lines) + "\n"


def _dashboard_status(events: list[Any], result: dict[str, Any] | None) -> str:
    if result is not None:
        return "blocked" if result.get("blocked") else "ok"
    if not events:
        return "pending"
    last = events[-1]
    if isinstance(last, dict) and last.get("phase") == "run" and last.get("status") in {"ok", "blocked", "failed"}:
        return str(last.get("status"))
    return "running"


def _last_elapsed_ms(events: list[Any]) -> int:
    for event in reversed(events):
        if isinstance(event, dict):
            return int(event.get("elapsed_ms") or 0)
    return 0


def _phase_timings(events: list[Any]) -> list[dict[str, Any]]:
    phases: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        phase = str(event.get("phase") or "run")
        elapsed_ms = int(event.get("elapsed_ms") or 0)
        if phase not in phases:
            order.append(phase)
            phases[phase] = {
                "phase": phase,
                "status": str(event.get("status") or ""),
                "first_elapsed_ms": elapsed_ms,
                "last_elapsed_ms": elapsed_ms,
                "duration_ms": 0,
                "event_count": 0,
                "last_message": "",
            }
        row = phases[phase]
        row["status"] = str(event.get("status") or "")
        row["last_elapsed_ms"] = elapsed_ms
        row["duration_ms"] = max(0, elapsed_ms - int(row["first_elapsed_ms"]))
        row["event_count"] = int(row["event_count"]) + 1
        row["last_message"] = str(event.get("message") or "")
    return [phases[phase] for phase in order]


def _live_look(events: list[Any], result: dict[str, Any] | None) -> dict[str, Any]:
    timeline = _live_timeline(events)
    system_health = _system_health_signals(events, result)
    headline = "Waiting for the first incident signal."
    if timeline:
        latest = timeline[-1]
        headline = "{elapsed} {phase} {status}: {message}".format(
            elapsed=latest["elapsed"],
            phase=latest["phase"],
            status=latest["status"],
            message=latest["message"] or latest["detail"] or "-",
        )
    return {
        "headline": headline,
        "system_health": system_health[-24:],
        "timeline": timeline[-12:],
    }


def _live_timeline(events: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        rows.append(
            {
                "elapsed": _format_elapsed(int(event.get("elapsed_ms") or 0)),
                "phase": event.get("phase") or "run",
                "status": event.get("status") or "-",
                "message": event.get("message") or "-",
                "detail": _live_detail_excerpt(details),
            }
        )
    return rows


def _system_health_signals(events: list[Any], result: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen_runtime_keys: set[tuple[str, str]] = set()
    for event in events:
        if not isinstance(event, dict):
            continue
        elapsed = _format_elapsed(int(event.get("elapsed_ms") or 0))
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        state = details.get("runtime_state")
        if isinstance(state, dict):
            for container in state.get("containers", []):
                if not isinstance(container, dict):
                    continue
                source = str(container.get("name") or "container")
                status = str(container.get("status") or event.get("status") or "observed")
                key = ("container", source)
                if key in seen_runtime_keys:
                    continue
                seen_runtime_keys.add(key)
                rows.append(
                    {
                        "elapsed": elapsed,
                        "source": source,
                        "signal": "container",
                        "status": status,
                        "detail": _compact(container.get("image") or container),
                    }
                )
            for image in state.get("images", []):
                if not isinstance(image, dict):
                    continue
                source = str(image.get("repository") or image.get("id") or "image")
                key = ("image", source)
                if key in seen_runtime_keys:
                    continue
                seen_runtime_keys.add(key)
                rows.append(
                    {
                        "elapsed": elapsed,
                        "source": source,
                        "signal": "image",
                        "status": "available",
                        "detail": _compact({"id": image.get("id"), "size": image.get("size")}),
                    }
                )
        if event.get("phase") == "wait_for":
            matched = details.get("matched")
            status = "matched" if matched is True else "observed" if event.get("status") == "observed" else event.get("status")
            rows.append(
                {
                    "elapsed": elapsed,
                    "source": details.get("scenario") or "-",
                    "signal": details.get("kind") or "wait_for",
                    "status": status or "-",
                    "detail": _compact(details.get("observed", details.get("failures", ""))),
                }
            )
        elif event.get("phase") == "seed":
            rows.append(
                {
                    "elapsed": elapsed,
                    "source": details.get("scenario") or "-",
                    "signal": "seed",
                    "status": event.get("status") or "-",
                    "detail": _compact(details.get("failures", event.get("message", ""))),
                }
            )
        elif event.get("phase") in {"teardown", "warm_kind_cleanup"}:
            rows.append(
                {
                    "elapsed": elapsed,
                    "source": details.get("scenario") or details.get("step") or "-",
                    "signal": event.get("phase") or "teardown",
                    "status": event.get("status") or "-",
                    "detail": _compact(details.get("failures", event.get("message", ""))),
                }
            )
    if result is not None:
        rows.append(
            {
                "elapsed": _format_elapsed(int(result.get("elapsed_ms") or 0)),
                "source": result.get("scenario") or result.get("incident_session_id") or "run",
                "signal": "result",
                "status": "blocked" if result.get("blocked") else "ok",
                "detail": _compact(
                    {
                        "failure_class": result.get("failure_class"),
                        "teardown_failures": result.get("teardown_failures"),
                    }
                ),
            }
        )
    return rows


def _live_detail_excerpt(details: dict[str, Any]) -> str:
    for key in ("observed", "runtime_state", "failures", "teardown", "failure_classification"):
        if key in details:
            return str(_compact(details[key]))
    compacted = _compact(details)
    return str(compacted) if compacted else "-"


def _runtime_state(events: list[Any]) -> dict[str, Any]:
    runtime: dict[str, Any] = {}
    for event in events:
        if not isinstance(event, dict):
            continue
        details = event.get("details")
        if not isinstance(details, dict):
            continue
        state = details.get("runtime_state")
        if isinstance(state, dict):
            runtime.update(_jsonable(state))
        for key in ("archetype", "kubeconfig_path", "compose_project"):
            if details.get(key):
                runtime.setdefault(key, details[key])
    return runtime


def _seed_checkpoints(events: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict) or event.get("phase") != "seed":
            continue
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        rows.append(
            {
                "scenario": details.get("scenario") or "-",
                "status": event.get("status"),
                "applied": details.get("applied"),
                "elapsed": _format_elapsed(int(event.get("elapsed_ms") or 0)),
                "failures": _compact(details.get("failures", [])),
            }
        )
    return rows


def _wait_predicates(events: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict) or event.get("phase") != "wait_for":
            continue
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        rows.append(
            {
                "scenario": details.get("scenario") or "-",
                "kind": details.get("kind") or "-",
                "status": event.get("status"),
                "matched": details.get("matched"),
                "observed": _compact(details.get("observed", details.get("failures", ""))),
                "elapsed": _format_elapsed(int(event.get("elapsed_ms") or 0)),
            }
        )
    return rows


def _teardown_status(events: list[Any], result: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict) or event.get("phase") not in {"teardown", "warm_kind_cleanup"}:
            continue
        details = event.get("details") if isinstance(event.get("details"), dict) else {}
        rows.append(
            {
                "phase": event.get("phase"),
                "step": details.get("step") or "-",
                "scenario": details.get("scenario") or "-",
                "status": event.get("status"),
                "failures": _compact(details.get("failures", [])),
                "elapsed": _format_elapsed(int(event.get("elapsed_ms") or 0)),
            }
        )
    if result is not None:
        context = result.get("context") if isinstance(result.get("context"), dict) else {}
        teardown = context.get("teardown") if isinstance(context.get("teardown"), dict) else None
        if teardown is not None:
            rows.append(
                {
                    "phase": "teardown",
                    "step": "result",
                    "scenario": result.get("scenario") or "-",
                    "status": "ok" if teardown.get("verified") else "failed",
                    "failures": _compact(teardown.get("failures", [])),
                    "elapsed": _format_elapsed(int(result.get("elapsed_ms") or 0)),
                }
            )
    return rows


def _markdown_rows(rows: Any, columns: tuple[str, ...]) -> list[str]:
    if not isinstance(rows, list) or not rows:
        return ["No entries yet."]
    lines = ["| " + " | ".join(column.replace("_", " ").title() for column in columns) + " |"]
    lines.append("| " + " | ".join("---" for _column in columns) + " |")
    for row in rows:
        mapping = row if isinstance(row, dict) else {}
        lines.append("| " + " | ".join(_md_text(mapping.get(column, "-")) for column in columns) + " |")
    return lines


def _md_code(value: Any) -> str:
    return "`" + str(value if value is not None else "-").replace("`", "'") + "`"


def _md_text(value: Any) -> str:
    text = str(value if value is not None else "-")
    text = text.replace("|", "\\|").replace("\n", " ")
    return text[:240] + "..." if len(text) > 240 else text


def _compact(value: Any, *, limit: int = 240) -> Any:
    if value in (None, "", [], {}):
        return ""
    rendered = json.dumps(_jsonable(value), sort_keys=True)
    return rendered[: limit - 3] + "..." if len(rendered) > limit else rendered


def _human_line(payload: dict[str, Any]) -> str:
    elapsed = _format_elapsed(int(payload.get("elapsed_ms") or 0))
    phase = str(payload.get("phase") or "run")
    status = str(payload.get("status") or "info")
    message = str(payload.get("message") or "")
    details = _format_details(payload.get("details") or {})
    parts = [f"[{elapsed}]", status, phase]
    if message:
        parts.append(message)
    if details:
        parts.append(details)
    return " ".join(parts)


def _format_elapsed(elapsed_ms: int) -> str:
    total_seconds = elapsed_ms // 1000
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes:02d}:{seconds:02d}"


def _format_details(details: Any) -> str:
    if not isinstance(details, dict) or not details:
        return ""
    simple: list[str] = []
    for key in sorted(details):
        value = details[key]
        if value is None:
            continue
        rendered = json.dumps(_jsonable(value), sort_keys=True)
        if len(rendered) > 160:
            rendered = rendered[:157] + "..."
        simple.append(f"{key}={rendered}")
    return " ".join(simple)


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except TypeError:
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, dict):
            return {str(key): _jsonable(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [_jsonable(item) for item in value]
        return str(value)


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip()).strip("-")
    return slug or "incident-generator-run"
