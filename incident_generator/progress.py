"""Operator progress reporting for incident generation runs."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, TextIO


PROGRESS_SCHEMA_VERSION = "incident-generator.progress/v1"


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
        self._clock = clock
        self._started = float(clock())
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
        if self.stream is not None and self.stream_format is not None:
            self._write_stream(payload)
        if self._events_file is not None:
            self._events_file.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")
            self._events_file.flush()

    def write_summary(self, result: dict[str, Any]) -> None:
        if self.summary_path is None:
            return
        self.summary_path.write_text(json.dumps(_jsonable(result), indent=2, sort_keys=True) + "\n", encoding="utf-8")

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


def default_artifact_dir(root: Path, incident_session_id: str) -> Path:
    return root / ".tmp" / "incidents" / _slug(incident_session_id or "incident-generator-run")


def progress_artifacts(reporter: Any) -> dict[str, str]:
    artifact_dir = getattr(reporter, "artifact_dir", None)
    events_path = getattr(reporter, "events_path", None)
    summary_path = getattr(reporter, "summary_path", None)
    artifacts: dict[str, str] = {}
    if artifact_dir is not None:
        artifacts["directory"] = str(artifact_dir)
    if events_path is not None:
        artifacts["events"] = str(events_path)
    if summary_path is not None:
        artifacts["summary"] = str(summary_path)
    return artifacts


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
