"""Terminal experience replay for retained incident-generator artifacts."""

from __future__ import annotations

import json
import re
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, TextIO

from .parsers import redact


EXPERIENCE_SCHEMA_VERSION = "incident-generator.experience/v1"
TIMELINE_EVENT_SCHEMA_VERSION = "incident-generator.experience-timeline-event/v1"
V2_SOURCE_MODE = "sandboxed_investigation_session"
V1_SOURCE_MODE = "redacted_evidence_bundle"
EVENTS_SOURCE_MODE = "events_ndjson"
DASHBOARD_SOURCE_MODE = "progress_dashboard"
RESULT_SOURCE_MODE = "benchmark_result"
FOLLOW_TERMINAL_STATUSES = {"ok", "blocked", "failed", "error"}
HIDDEN_ANSWER_FIELDS = {
    "answer_key",
    "expected_hypotheses",
    "forbidden_hypotheses",
    "hidden_answers",
    "internal_evidence_roles",
    "evidence_role_expectations",
    "internal_signal_role",
    "scoring_labels",
    "signal_role_counts",
}
STREAMS = {"agent", "inspect", "evidence", "action", "gate", "judge", "logs", "metrics", "traffic", "gap"}


class ExperienceError(ValueError):
    """Raised when an artifact directory cannot be replayed."""


def run_tail_experience(
    artifact_dir: Path,
    *,
    output_dir: Path | None = None,
    generated_at: str | None = None,
    speed: float = 1.0,
    max_gap_seconds: float = 30.0,
    no_sleep: bool = False,
    no_play: bool = False,
    stream: TextIO | None = None,
) -> dict[str, Any]:
    """Build, optionally write, and optionally play a terminal-tail experience."""

    payload, timeline = build_tail_experience(
        artifact_dir,
        generated_at=generated_at,
        speed=speed,
        max_gap_seconds=max_gap_seconds,
    )
    if output_dir is not None:
        write_experience_artifacts(output_dir, payload, timeline)
    if not no_play:
        play_tail_timeline(timeline, no_sleep=no_sleep, stream=stream or sys.stdout)
    return payload


def run_follow_experience(
    artifact_dir: Path,
    *,
    output_dir: Path | None = None,
    generated_at: str | None = None,
    speed: float = 1.0,
    max_gap_seconds: float = 30.0,
    poll_interval_seconds: float = 1.0,
    timeout_seconds: float | None = None,
    idle_timeout_seconds: float | None = None,
    no_play: bool = False,
    stream: TextIO | None = None,
    sleep_func: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Follow appended retained artifact events, then leave a replayable timeline."""

    if speed <= 0:
        raise ExperienceError("--speed must be greater than 0")
    if max_gap_seconds < 0:
        raise ExperienceError("--max-gap-seconds must be greater than or equal to 0")
    if poll_interval_seconds < 0:
        raise ExperienceError("--poll-interval-seconds must be greater than or equal to 0")
    if timeout_seconds is not None and timeout_seconds < 0:
        raise ExperienceError("--follow-timeout-seconds must be greater than or equal to 0")
    if idle_timeout_seconds is not None and idle_timeout_seconds < 0:
        raise ExperienceError("--follow-idle-timeout-seconds must be greater than or equal to 0")
    artifact_dir = artifact_dir.resolve()
    if not artifact_dir.is_dir():
        raise ExperienceError(f"artifact directory does not exist: {artifact_dir}")
    generated = generated_at or _utc_now()
    stream = stream or sys.stdout
    started_monotonic = time.monotonic()
    last_new_monotonic = started_monotonic
    printed_count = 0
    last_payload: dict[str, Any] | None = None
    last_timeline: list[dict[str, Any]] = []
    events_path = artifact_dir / "events.ndjson"

    while True:
        now = time.monotonic()
        if events_path.is_file():
            rows = _load_ndjson_for_follow(events_path)
            if rows:
                raw_events = _events_from_ndjson_rows(
                    artifact_dir,
                    rows,
                    source_path=_relative(events_path, artifact_dir),
                    generated_at=generated,
                )
                timeline = _timeline_from_events(
                    raw_events,
                    source_mode=EVENTS_SOURCE_MODE,
                    speed=speed,
                    max_gap_seconds=max_gap_seconds,
                )
                complete = _follow_is_complete(artifact_dir, rows)
                new_events = timeline[printed_count:]
                if new_events:
                    if not no_play:
                        play_tail_timeline(new_events, no_sleep=True, stream=stream)
                    printed_count = len(timeline)
                    last_new_monotonic = now
                last_timeline = timeline
                last_payload = _follow_payload(
                    artifact_dir,
                    generated_at=generated,
                    timeline=timeline,
                    state="completed" if complete else "running",
                    speed=speed,
                    max_gap_seconds=max_gap_seconds,
                    poll_interval_seconds=poll_interval_seconds,
                    timeout_seconds=timeout_seconds,
                    idle_timeout_seconds=idle_timeout_seconds,
                    fallback_replay=False,
                )
                if output_dir is not None:
                    write_experience_artifacts(output_dir, last_payload, last_timeline)
                if complete:
                    return last_payload
        elif _has_post_run_replay_artifact(artifact_dir):
            payload, timeline = build_tail_experience(
                artifact_dir,
                generated_at=generated,
                speed=speed,
                max_gap_seconds=max_gap_seconds,
            )
            payload = dict(payload)
            payload["mode"] = "follow"
            payload["follow"] = {
                "state": "fallback_replay",
                "reason": "events.ndjson was not present; used post-run replay artifacts",
                "events_path": _relative(events_path, artifact_dir),
                "fallback_replay": True,
            }
            if output_dir is not None:
                write_experience_artifacts(output_dir, payload, timeline)
            if not no_play:
                play_tail_timeline(timeline, no_sleep=True, stream=stream)
            return payload

        now = time.monotonic()
        if timeout_seconds is not None and now - started_monotonic >= timeout_seconds:
            if last_payload is not None:
                last_payload = dict(last_payload)
                last_payload["follow"] = dict(last_payload.get("follow", {}))
                last_payload["follow"]["state"] = "timeout"
                if output_dir is not None:
                    write_experience_artifacts(output_dir, last_payload, last_timeline)
                return last_payload
            raise ExperienceError("follow timed out before replayable events were available")
        if (
            idle_timeout_seconds is not None
            and last_payload is not None
            and now - last_new_monotonic >= idle_timeout_seconds
        ):
            last_payload = dict(last_payload)
            last_payload["follow"] = dict(last_payload.get("follow", {}))
            last_payload["follow"]["state"] = "idle_timeout"
            if output_dir is not None:
                write_experience_artifacts(output_dir, last_payload, last_timeline)
            return last_payload
        sleep_func(poll_interval_seconds)


def build_tail_experience(
    artifact_dir: Path,
    *,
    generated_at: str | None = None,
    speed: float = 1.0,
    max_gap_seconds: float = 30.0,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if speed <= 0:
        raise ExperienceError("--speed must be greater than 0")
    if max_gap_seconds < 0:
        raise ExperienceError("--max-gap-seconds must be greater than or equal to 0")
    artifact_dir = artifact_dir.resolve()
    if not artifact_dir.is_dir():
        raise ExperienceError(f"artifact directory does not exist: {artifact_dir}")
    generated = generated_at or _utc_now()
    raw_events, source_mode = _load_source_events(artifact_dir, generated_at=generated)
    timeline = _timeline_from_events(
        raw_events,
        source_mode=source_mode,
        speed=speed,
        max_gap_seconds=max_gap_seconds,
    )
    stream_counts = Counter(event["stream"] for event in timeline)
    payload = {
        "schema_version": EXPERIENCE_SCHEMA_VERSION,
        "mode": "tail",
        "source_mode": source_mode,
        "artifact_dir": str(artifact_dir),
        "generated_at": generated,
        "event_count": len(timeline),
        "stream_counts": dict(sorted(stream_counts.items())),
        "options": {
            "speed": speed,
            "max_gap_seconds": max_gap_seconds,
        },
        "artifacts": {
            "experience": "experience.json",
            "timeline": "timeline.ndjson",
        },
    }
    return payload, timeline


def write_experience_artifacts(output_dir: Path, payload: Mapping[str, Any], timeline: list[Mapping[str, Any]]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "experience.json").write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "timeline.ndjson").write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in timeline),
        encoding="utf-8",
    )


def play_tail_timeline(timeline: list[Mapping[str, Any]], *, no_sleep: bool, stream: TextIO) -> None:
    for event in timeline:
        sleep_seconds = float(event.get("sleep_seconds") or 0)
        if sleep_seconds > 0 and not no_sleep:
            time.sleep(sleep_seconds)
        print(event.get("line") or _format_line(event), file=stream, flush=True)


def _load_source_events(artifact_dir: Path, *, generated_at: str) -> tuple[list[dict[str, Any]], str]:
    transcript_paths = _investigation_transcript_paths(artifact_dir)
    if transcript_paths:
        events: list[dict[str, Any]] = []
        for path in transcript_paths:
            events.extend(_events_from_investigation_transcript(artifact_dir, path, generated_at=generated_at))
        trace_path = artifact_dir / "trace.json"
        if trace_path.is_file():
            events.extend(_events_from_trace_annotations(artifact_dir, trace_path, generated_at=generated_at, events=events))
        result_path = artifact_dir / "result.json"
        if result_path.is_file() and not trace_path.is_file():
            events.extend(_events_from_result(artifact_dir, result_path, generated_at=generated_at, events=events))
        return events, V2_SOURCE_MODE
    trace_path = artifact_dir / "trace.json"
    if trace_path.is_file():
        return _events_from_trace(artifact_dir, trace_path, generated_at=generated_at)
    dashboard_path = artifact_dir / "dashboard.json"
    result_path = artifact_dir / "result.json"
    if dashboard_path.is_file():
        events = _events_from_dashboard(artifact_dir, dashboard_path, generated_at=generated_at)
        events.extend(_events_from_optional_live_metadata(artifact_dir, generated_at=generated_at, events=events))
        if result_path.is_file():
            events.extend(_events_from_result(artifact_dir, result_path, generated_at=generated_at, events=events))
        return events, DASHBOARD_SOURCE_MODE
    if result_path.is_file():
        events = _events_from_result(artifact_dir, result_path, generated_at=generated_at, events=[])
        events.extend(_events_from_optional_live_metadata(artifact_dir, generated_at=generated_at, events=events))
        return events, RESULT_SOURCE_MODE
    events_path = artifact_dir / "events.ndjson"
    if events_path.is_file():
        return _events_from_ndjson(artifact_dir, events_path, generated_at=generated_at), EVENTS_SOURCE_MODE
    raise ExperienceError(
        "artifact directory must contain investigation-transcript.ndjson, trace.json, dashboard.json, result.json, or events.ndjson"
    )


def _investigation_transcript_paths(artifact_dir: Path) -> list[Path]:
    paths = []
    direct = artifact_dir / "investigation-transcript.ndjson"
    if direct.is_file():
        paths.append(direct)
    paths.extend(sorted(artifact_dir.glob("cases/*/investigation-transcript.ndjson")))
    return sorted(paths)


def _events_from_investigation_transcript(
    artifact_dir: Path,
    path: Path,
    *,
    generated_at: str,
) -> list[dict[str, Any]]:
    return _events_from_investigation_rows(
        artifact_dir,
        _load_ndjson(path),
        source_path=_relative(path, artifact_dir),
        generated_at=generated_at,
    )


def _events_from_investigation_rows(
    artifact_dir: Path,
    rows: list[dict[str, Any]],
    *,
    source_path: str,
    generated_at: str,
) -> list[dict[str, Any]]:
    del artifact_dir
    events = []
    for index, row in enumerate(rows):
        stream = _stream(row.get("stream"), default="agent")
        timestamp = _timestamp_for(row, generated_at=generated_at, fallback_offset_ms=index * 1000)
        summary = _safe_text(row.get("summary") or row.get("event_type") or stream)
        events.append(
            {
                "timestamp": timestamp,
                "stream": stream,
                "event_type": _safe_token(row.get("event_type") or "event"),
                "summary": summary,
                "source_ref": row.get("source_ref") if isinstance(row.get("source_ref"), str) else source_path,
                "source_path": source_path,
                "source_sequence": _int(row.get("seq"), default=index + 1),
                "redacted": row.get("redacted") is not False,
            }
        )
    return events


def _events_from_ndjson(artifact_dir: Path, path: Path, *, generated_at: str) -> list[dict[str, Any]]:
    rows = _load_ndjson(path)
    return _events_from_ndjson_rows(
        artifact_dir,
        rows,
        source_path=_relative(path, artifact_dir),
        generated_at=generated_at,
    )


def _events_from_ndjson_rows(
    artifact_dir: Path,
    rows: list[dict[str, Any]],
    *,
    source_path: str,
    generated_at: str,
) -> list[dict[str, Any]]:
    del artifact_dir
    events = []
    for index, row in enumerate(rows):
        stream = _stream(row.get("stream") or row.get("phase"), default="agent")
        timestamp = _timestamp_for(row, generated_at=generated_at, fallback_offset_ms=index * 1000)
        phase = _safe_token(row.get("phase") or row.get("event") or row.get("event_type") or "event")
        status = _safe_token(row.get("status") or "")
        summary = _safe_text(row.get("summary") or row.get("message") or _compact_event_name(phase, status))
        events.append(
            {
                "timestamp": timestamp,
                "stream": stream,
                "event_type": status and f"{phase}.{status}" or phase,
                "summary": summary,
                "source_ref": source_path,
                "source_path": source_path,
                "source_sequence": index + 1,
                "redacted": True,
            }
        )
    return events


def _events_from_trace(artifact_dir: Path, path: Path, *, generated_at: str) -> tuple[list[dict[str, Any]], str]:
    trace = _load_json_object(path, label="trace.json")
    cases = trace.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ExperienceError("trace.json does not contain replayable cases")
    events: list[dict[str, Any]] = []
    for case in cases:
        if not isinstance(case, Mapping):
            continue
        if _trace_case_is_v2(case):
            transcript = case.get("investigation_transcript") if isinstance(case.get("investigation_transcript"), list) else []
            rows = [item for item in transcript if isinstance(item, dict)]
            if rows:
                events.extend(
                    _events_from_investigation_rows(
                        artifact_dir,
                        rows,
                        source_path=_string(case.get("investigation_transcript_ref")) or _relative(path, artifact_dir),
                        generated_at=generated_at,
                    )
                )
            else:
                events.extend(_trace_v2_prompt_events(artifact_dir, path, case, generated_at=generated_at, events=events))
            events.extend(_trace_case_annotations(artifact_dir, path, case, generated_at=generated_at, events=events))
            continue
        events.extend(_trace_v1_compatibility_events(artifact_dir, path, case, generated_at=generated_at, events=events))
        events.extend(_trace_case_annotations(artifact_dir, path, case, generated_at=generated_at, events=events))
    source_mode = V2_SOURCE_MODE if any(isinstance(case, Mapping) and _trace_case_is_v2(case) for case in cases) else V1_SOURCE_MODE
    return events, source_mode


def _events_from_trace_annotations(
    artifact_dir: Path,
    path: Path,
    *,
    generated_at: str,
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    trace = _load_json_object(path, label="trace.json")
    cases = trace.get("cases")
    if not isinstance(cases, list):
        return []
    annotations: list[dict[str, Any]] = []
    for case in cases:
        if isinstance(case, Mapping):
            annotations.extend(
                _trace_case_annotations(
                    artifact_dir,
                    path,
                    case,
                    generated_at=generated_at,
                    events=events + annotations,
                )
            )
    return annotations


def _trace_case_is_v2(case: Mapping[str, Any]) -> bool:
    prompt = case.get("agent_prompt") if isinstance(case.get("agent_prompt"), Mapping) else {}
    return (
        prompt.get("input_mode") == V2_SOURCE_MODE
        or case.get("source_mode") == V2_SOURCE_MODE
        or bool(case.get("investigation_transcript"))
    )


def _trace_v2_prompt_events(
    artifact_dir: Path,
    path: Path,
    case: Mapping[str, Any],
    *,
    generated_at: str,
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    prompt = case.get("agent_prompt") if isinstance(case.get("agent_prompt"), Mapping) else {}
    case_id = _safe_text(case.get("case_id") or "case")
    alert = prompt.get("initial_alert") if isinstance(prompt.get("initial_alert"), Mapping) else {}
    tool_catalog = prompt.get("tool_catalog") if isinstance(prompt.get("tool_catalog"), list) else []
    output = [
        _raw_event_after(
            events,
            generated_at,
            "agent",
            "session_start",
            f"responder starts from alert for {case_id}: {_safe_text(alert.get('symptom') or alert.get('summary') or 'incident alert')}",
            _string(case.get("session_start_ref")) or _relative(path, artifact_dir),
        )
    ]
    if tool_catalog:
        output.append(
            _raw_event_after(
                events + output,
                generated_at,
                "inspect",
                "tool_catalog",
                f"read-only tool catalog advertised {len(tool_catalog)} fixture-safe tools",
                _relative(path, artifact_dir),
            )
        )
    return output


def _trace_v1_compatibility_events(
    artifact_dir: Path,
    path: Path,
    case: Mapping[str, Any],
    *,
    generated_at: str,
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    source_ref = _relative(path, artifact_dir)
    case_id = _safe_text(case.get("case_id") or "case")
    output.append(
        _raw_event_after(
            events + output,
            generated_at,
            "agent",
            "compatibility_replay",
            f"compatibility replay for {case_id}; investigation transcript unavailable",
            source_ref,
        )
    )
    prompt = case.get("agent_prompt") if isinstance(case.get("agent_prompt"), Mapping) else {}
    for item in prompt.get("evidence_items", []) if isinstance(prompt.get("evidence_items"), list) else []:
        if not isinstance(item, Mapping):
            continue
        title = _safe_text(item.get("title") or item.get("evidence_id") or "redacted evidence snapshot")
        source = _safe_text(item.get("adapter_id") or item.get("source_kind") or "source")
        output.append(
            _raw_event_after(
                events + output,
                generated_at,
                "evidence",
                "compatibility_snapshot",
                f"compatibility evidence snapshot from {source}: {title}",
                source_ref,
            )
        )
    response = case.get("agent_response") if isinstance(case.get("agent_response"), Mapping) else {}
    hypothesis = _first_hypothesis_summary(response)
    if hypothesis:
        output.append(
            _raw_event_after(
                events + output,
                generated_at,
                "agent",
                "final_response",
                hypothesis,
                source_ref,
            )
        )
    return output


def _trace_case_annotations(
    artifact_dir: Path,
    path: Path,
    case: Mapping[str, Any],
    *,
    generated_at: str,
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    source_ref = _relative(path, artifact_dir)
    case_id = _safe_text(case.get("case_id") or "case")
    response = case.get("agent_response") if isinstance(case.get("agent_response"), Mapping) else {}
    for action in response.get("proposed_actions", []) if isinstance(response.get("proposed_actions"), list) else []:
        if not isinstance(action, Mapping):
            continue
        summary = _safe_text(action.get("summary") or action.get("action_id") or "proposed action")
        action_class = _safe_text(action.get("action_class") if action.get("action_class") is not None else "")
        suffix = f" class {action_class}" if action_class else ""
        output.append(
            _raw_event_after(
                events + output,
                generated_at,
                "action",
                "proposed_action",
                f"{case_id}: {summary}{suffix}",
                _string(case.get("response_ref")) or source_ref,
            )
        )
    judge = case.get("judge") if isinstance(case.get("judge"), Mapping) else {}
    outcome = judge.get("outcome") if isinstance(judge.get("outcome"), Mapping) else {}
    scoring = judge.get("scoring") if isinstance(judge.get("scoring"), Mapping) else {}
    if outcome:
        status = _safe_text(outcome.get("status") or "judge")
        verdict = _safe_text(outcome.get("verdict") or "")
        score = _safe_text(outcome.get("score") if outcome.get("score") is not None else "")
        parts = [f"{case_id}: judge {status}"]
        if verdict:
            parts.append(f"verdict {verdict}")
        if score:
            parts.append(f"score {score}")
        output.append(
            _raw_event_after(events + output, generated_at, "judge", "judge_outcome", "; ".join(parts), source_ref)
        )
    state = _safe_text(case.get("state") or "")
    if state or isinstance(scoring.get("overall_pass"), bool):
        if isinstance(scoring.get("overall_pass"), bool):
            gate_summary = "passed" if scoring.get("overall_pass") else "failed"
        else:
            gate_summary = state or "recorded"
        output.append(
            _raw_event_after(
                events + output,
                generated_at,
                "gate",
                "benchmark_gate",
                f"{case_id}: benchmark gate {gate_summary}",
                source_ref,
            )
        )
    return output


def _events_from_dashboard(artifact_dir: Path, path: Path, *, generated_at: str) -> list[dict[str, Any]]:
    dashboard = _load_json_object(path, label="dashboard.json")
    source_ref = _relative(path, artifact_dir)
    events: list[dict[str, Any]] = []

    live_look = dashboard.get("live_look") if isinstance(dashboard.get("live_look"), Mapping) else {}
    for row in live_look.get("timeline", []) if isinstance(live_look.get("timeline"), list) else []:
        if not isinstance(row, Mapping):
            continue
        phase = _safe_token(row.get("phase") or "run")
        status = _safe_token(row.get("status") or "")
        message = _safe_text(row.get("message") or row.get("detail") or _compact_event_name(phase, status))
        detail = _safe_text(row.get("detail") or "")
        summary = message if not detail or detail == "-" else f"{message}; {detail}"
        events.append(
            _raw_event_at_elapsed(
                generated_at,
                _elapsed_to_ms(row.get("elapsed"), default=len(events) * 1000),
                _dashboard_phase_stream(phase, status),
                status and f"{phase}.{status}" or phase,
                summary,
                source_ref,
                len(events) + 1,
            )
        )
    for row in live_look.get("system_health", []) if isinstance(live_look.get("system_health"), list) else []:
        if not isinstance(row, Mapping):
            continue
        signal = _safe_token(row.get("signal") or "signal")
        source = _safe_text(row.get("source") or "source")
        status = _safe_text(row.get("status") or "observed")
        detail = _safe_text(row.get("detail") or "")
        summary = f"{source} {signal} {status}"
        if detail and detail != "-":
            summary = f"{summary}: {detail}"
        events.append(
            _raw_event_at_elapsed(
                generated_at,
                _elapsed_to_ms(row.get("elapsed"), default=len(events) * 1000),
                _dashboard_signal_stream(signal, source, detail),
                f"system_health.{signal}",
                summary,
                source_ref,
                len(events) + 1,
            )
        )
    for row in dashboard.get("phase_timings", []) if isinstance(dashboard.get("phase_timings"), list) else []:
        if not isinstance(row, Mapping):
            continue
        phase = _safe_token(row.get("phase") or "run")
        status = _safe_token(row.get("status") or "")
        message = _safe_text(row.get("last_message") or _compact_event_name(phase, status))
        events.append(
            _raw_event_at_elapsed(
                generated_at,
                _int(row.get("last_elapsed_ms"), default=len(events) * 1000),
                _dashboard_phase_stream(phase, status),
                status and f"{phase}.{status}" or phase,
                message,
                source_ref,
                len(events) + 1,
            )
        )
    for row in dashboard.get("seed_checkpoints", []) if isinstance(dashboard.get("seed_checkpoints"), list) else []:
        if not isinstance(row, Mapping):
            continue
        scenario = _safe_text(row.get("scenario") or "scenario")
        status = _safe_text(row.get("status") or "observed")
        applied = row.get("applied")
        applied_text = "applied" if applied is True else "not yet applied" if applied is False else "observed"
        events.append(
            _raw_event_at_elapsed(
                generated_at,
                _elapsed_to_ms(row.get("elapsed"), default=len(events) * 1000),
                "inspect",
                "seed_checkpoint",
                f"{scenario} seed {status}: {applied_text}",
                source_ref,
                len(events) + 1,
            )
        )
    for row in dashboard.get("wait_predicates", []) if isinstance(dashboard.get("wait_predicates"), list) else []:
        if not isinstance(row, Mapping):
            continue
        kind = _safe_token(row.get("kind") or "wait_for")
        scenario = _safe_text(row.get("scenario") or "scenario")
        status = _safe_text(row.get("status") or "observed")
        observed = _safe_text(row.get("observed") or "")
        summary = f"{scenario} {kind} {status}"
        if observed:
            summary = f"{summary}: {observed}"
        events.append(
            _raw_event_at_elapsed(
                generated_at,
                _elapsed_to_ms(row.get("elapsed"), default=len(events) * 1000),
                _dashboard_signal_stream(kind, scenario, observed),
                f"wait_for.{kind}",
                summary,
                source_ref,
                len(events) + 1,
            )
        )
    runtime = dashboard.get("runtime_state") if isinstance(dashboard.get("runtime_state"), Mapping) else {}
    for container in runtime.get("containers", []) if isinstance(runtime.get("containers"), list) else []:
        if not isinstance(container, Mapping):
            continue
        events.append(
            _raw_event_at_elapsed(
                generated_at,
                _int(dashboard.get("elapsed_ms"), default=len(events) * 1000),
                "metrics",
                "runtime_container",
                f"{_safe_text(container.get('name') or 'container')} {_safe_text(container.get('status') or 'observed')}",
                source_ref,
                len(events) + 1,
            )
        )
    dashboard_status = _safe_text(dashboard.get("status") or "")
    if dashboard_status:
        failure_class = _safe_text(dashboard.get("failure_class") or "")
        summary = f"progress dashboard status {dashboard_status}"
        if failure_class and failure_class != "none":
            summary = f"{summary}; failure class {failure_class}"
        events.append(
            _raw_event_at_elapsed(
                generated_at,
                _int(dashboard.get("elapsed_ms"), default=len(events) * 1000),
                "gate",
                "progress_status",
                summary,
                source_ref,
                len(events) + 1,
            )
        )
    return events


def _events_from_result(
    artifact_dir: Path,
    path: Path,
    *,
    generated_at: str,
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result = _load_json_object(path, label="result.json")
    if result.get("schema_version") == "incident-generator.benchmark-result/v1" or isinstance(result.get("results"), list):
        return _events_from_benchmark_result(artifact_dir, path, result, generated_at=generated_at, events=events)
    return _events_from_run_result(artifact_dir, path, result, generated_at=generated_at, events=events)


def _events_from_benchmark_result(
    artifact_dir: Path,
    path: Path,
    result: Mapping[str, Any],
    *,
    generated_at: str,
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    source_ref = _relative(path, artifact_dir)
    output: list[dict[str, Any]] = []
    for case in result.get("cases", []) if isinstance(result.get("cases"), list) else []:
        if not isinstance(case, Mapping):
            continue
        case_id = _safe_text(case.get("case_id") or "case")
        generated_incident = case.get("generated_incident") if isinstance(case.get("generated_incident"), Mapping) else {}
        collection_mode = _safe_text(generated_incident.get("collection_mode") or "")
        generation_state = _safe_text(generated_incident.get("generation_state") or "")
        if collection_mode or generation_state:
            output.append(
                _raw_event_after(
                    events + output,
                    generated_at,
                    "inspect",
                    "case_metadata",
                    f"{case_id}: read-only generated incident metadata {collection_mode or 'fixture'} {generation_state or 'recorded'}",
                    source_ref,
                )
            )
        for ref in generated_incident.get("artifact_refs", []) if isinstance(generated_incident.get("artifact_refs"), list) else []:
            if not isinstance(ref, Mapping):
                continue
            output.append(
                _raw_event_after(
                    events + output,
                    generated_at,
                    "inspect",
                    "artifact_ref",
                    f"{case_id}: read-only artifact { _safe_text(ref.get('kind') or 'artifact') } retained at {_safe_text(ref.get('ref') or '-')}",
                    source_ref,
                )
            )
    for row in result.get("results", []) if isinstance(result.get("results"), list) else []:
        if not isinstance(row, Mapping):
            continue
        case_id = _safe_text(row.get("case_id") or "case")
        state = _safe_text(row.get("state") or "")
        if state:
            output.append(
                _raw_event_after(
                    events + output,
                    generated_at,
                    "agent",
                    "result_state",
                    f"{case_id}: entrant result {state}",
                    _string(row.get("agent_output_ref")) or source_ref,
                )
            )
        diagnosis = row.get("diagnosis") if isinstance(row.get("diagnosis"), Mapping) else {}
        evidence_refs = diagnosis.get("evidence_refs") if isinstance(diagnosis.get("evidence_refs"), list) else []
        visible_refs = [_safe_text(item) for item in evidence_refs if isinstance(item, str)]
        if visible_refs:
            output.append(
                _raw_event_after(
                    events + output,
                    generated_at,
                    "evidence",
                    "cited_evidence",
                    f"{case_id}: read-only evidence refs cited {', '.join(visible_refs[:5])}",
                    source_ref,
                )
            )
        judge = row.get("judge_outcome") if isinstance(row.get("judge_outcome"), Mapping) else {}
        if judge:
            status = _safe_text(judge.get("status") or "judge")
            verdict = _safe_text(judge.get("verdict") or "")
            output.append(
                _raw_event_after(
                    events + output,
                    generated_at,
                    "judge",
                    "judge_outcome",
                    f"{case_id}: judge {status}{f' verdict {verdict}' if verdict else ''}",
                    source_ref,
                )
            )
        scoring = row.get("scoring") if isinstance(row.get("scoring"), Mapping) else {}
        if isinstance(scoring.get("overall_pass"), bool) or state:
            gate = "passed" if scoring.get("overall_pass") is True else "failed" if scoring.get("overall_pass") is False else state
            output.append(
                _raw_event_after(
                    events + output,
                    generated_at,
                    "gate",
                    "benchmark_gate",
                    f"{case_id}: benchmark gate {gate}",
                    source_ref,
                )
            )
    return output


def _events_from_run_result(
    artifact_dir: Path,
    path: Path,
    result: Mapping[str, Any],
    *,
    generated_at: str,
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    source_ref = _relative(path, artifact_dir)
    output: list[dict[str, Any]] = []
    scenario = _safe_text(result.get("scenario") or result.get("incident_id") or "incident")
    collection_mode = _safe_text(result.get("collection_mode") or "")
    service = _safe_text(result.get("service_id") or "")
    archetype = _safe_text(result.get("environment_archetype") or "")
    details = " ".join(part for part in [collection_mode, archetype, service] if part)
    output.append(
        _raw_event_after(
            events + output,
            generated_at,
            "inspect",
            "run_metadata",
            f"{scenario}: read-only run metadata{f' {details}' if details else ''}",
            source_ref,
        )
    )
    if scenario:
        output.append(
            _raw_event_after(
                events + output,
                generated_at,
                "evidence",
                "retained_symptom",
                f"retained incident symptom context for {scenario}",
                source_ref,
            )
        )
    state = "blocked" if result.get("blocked") else "ok" if result.get("generated") is True else "recorded"
    failure_class = _safe_text(result.get("failure_class") or "")
    output.append(
        _raw_event_after(
            events + output,
            generated_at,
            "gate",
            "run_result",
            f"{scenario}: run result {state}{f'; failure class {failure_class}' if failure_class and failure_class != 'none' else ''}",
            source_ref,
        )
    )
    context = result.get("context") if isinstance(result.get("context"), Mapping) else {}
    provider_profile = _safe_text(context.get("provider_profile") or context.get("active_provider_profile") or "")
    if provider_profile:
        output.append(
            _raw_event_after(
                events + output,
                generated_at,
                "inspect",
                "provider_profile",
                f"{scenario}: read-only provider profile {provider_profile}",
                source_ref,
            )
        )
    return output


def _events_from_optional_live_metadata(
    artifact_dir: Path,
    *,
    generated_at: str,
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    loadgen_path = artifact_dir / "loadgen-preview.json"
    if loadgen_path.is_file():
        output.extend(_events_from_loadgen_preview(artifact_dir, loadgen_path, generated_at=generated_at, events=events + output))
    noisy_path = artifact_dir / "noisy-smoke-report.json"
    if noisy_path.is_file():
        output.extend(_events_from_noisy_smoke_report(artifact_dir, noisy_path, generated_at=generated_at, events=events + output))
    return output


def _events_from_loadgen_preview(
    artifact_dir: Path,
    path: Path,
    *,
    generated_at: str,
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    payload = _load_json_object(path, label="loadgen-preview.json")
    source_ref = _relative(path, artifact_dir)
    output: list[dict[str, Any]] = []
    duration = _int(payload.get("duration_seconds"), default=0)
    concurrency = _int(payload.get("concurrency"), default=0)
    counts = payload.get("counts_by_route") if isinstance(payload.get("counts_by_route"), Mapping) else {}
    total = sum(value for value in counts.values() if isinstance(value, int))
    rps = round(total / duration, 1) if duration > 0 and total > 0 else None
    routes = ", ".join(_safe_text(key) for key in list(counts.keys())[:5])
    summary = "background workload preview"
    if rps is not None:
        summary = f"{summary}: {rps} rps"
    if concurrency:
        summary = f"{summary}, concurrency {concurrency}"
    if routes:
        summary = f"{summary}, routes {routes}"
    output.append(_raw_event_after(events + output, generated_at, "traffic", "background_workload", summary, source_ref))
    requests = payload.get("requests") if isinstance(payload.get("requests"), list) else []
    for request in requests[:3]:
        if not isinstance(request, Mapping):
            continue
        route = _safe_text(request.get("route") or "request")
        url = _safe_text(request.get("url") or "")
        output.append(
            _raw_event_at_elapsed(
                generated_at,
                _int(request.get("due_ms"), default=len(events + output) * 1000),
                "traffic",
                "request_preview",
                f"{route} request scheduled{f' {url}' if url else ''}",
                source_ref,
                len(events + output) + 1,
            )
        )
    return output


def _events_from_noisy_smoke_report(
    artifact_dir: Path,
    path: Path,
    *,
    generated_at: str,
    events: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    payload = _load_json_object(path, label="noisy-smoke-report.json")
    source_ref = _relative(path, artifact_dir)
    output: list[dict[str, Any]] = []
    target = payload.get("target") if isinstance(payload.get("target"), Mapping) else {}
    service = _safe_text(target.get("main_service") or "service")
    workload = _safe_text(target.get("workload") or "")
    load_generator = target.get("load_generator") if isinstance(target.get("load_generator"), Mapping) else {}
    rps = _safe_text(load_generator.get("rps") if load_generator.get("rps") is not None else "")
    if service or workload or rps:
        summary = f"background workload retained for {service}"
        if workload:
            summary = f"{summary} on {workload}"
        if rps:
            summary = f"{summary} at {rps} rps"
        output.append(_raw_event_after(events + output, generated_at, "traffic", "background_workload", summary, source_ref))
    scenarios = payload.get("scenarios") if isinstance(payload.get("scenarios"), list) else []
    for scenario in scenarios[:5]:
        if not isinstance(scenario, Mapping):
            continue
        noisy_fixture = scenario.get("noisy_fixture") if isinstance(scenario.get("noisy_fixture"), Mapping) else {}
        evidence_count = noisy_fixture.get("evidence_count")
        if isinstance(evidence_count, int):
            output.append(
                _raw_event_after(
                    events + output,
                    generated_at,
                    "evidence",
                    "noisy_fixture",
                    f"{_safe_text(scenario.get('scenario') or 'scenario')}: retained {evidence_count} redacted fixture evidence items",
                    source_ref,
                )
            )
        profile = scenario.get("workload_profile") if isinstance(scenario.get("workload_profile"), Mapping) else {}
        noise_profile = _safe_text(profile.get("noise_profile_id") or "")
        if noise_profile:
            output.append(
                _raw_event_after(
                    events + output,
                    generated_at,
                    _noise_profile_stream(noise_profile),
                    "background_noise",
                    f"{_safe_text(scenario.get('scenario') or 'scenario')}: background {noise_profile} profile retained",
                    source_ref,
                )
            )
    return output


def _timeline_from_events(
    events: list[dict[str, Any]],
    *,
    source_mode: str,
    speed: float,
    max_gap_seconds: float,
) -> list[dict[str, Any]]:
    if not events:
        raise ExperienceError("artifact source did not contain replayable events")
    sorted_events = sorted(events, key=lambda item: (item["timestamp"], item.get("source_path", ""), item["source_sequence"]))
    started = sorted_events[0]["timestamp"]
    previous = started
    timeline: list[dict[str, Any]] = []
    for raw in sorted_events:
        delay = max(0.0, (raw["timestamp"] - previous).total_seconds())
        event_sleep = round(delay / speed, 3)
        source_ref = _source_ref(raw)
        if timeline and delay > max_gap_seconds:
            gap = _timeline_event(
                sequence=len(timeline) + 1,
                timestamp=raw["timestamp"],
                started=started,
                stream="gap",
                event_type="time_gap",
                summary=f"{_format_duration(delay)} later (compressed)",
                source_mode=source_mode,
                source_ref=source_ref,
                delay_seconds=delay,
                sleep_seconds=0.0,
            )
            timeline.append(gap)
            event_sleep = round(min(delay / speed, max_gap_seconds), 3)
        timeline.append(
            _timeline_event(
                sequence=len(timeline) + 1,
                timestamp=raw["timestamp"],
                started=started,
                stream=raw["stream"],
                event_type=raw["event_type"],
                summary=raw["summary"],
                source_mode=source_mode,
                source_ref=source_ref,
                delay_seconds=delay,
                sleep_seconds=event_sleep,
            )
        )
        previous = raw["timestamp"]
    return timeline


def _timeline_event(
    *,
    sequence: int,
    timestamp: datetime,
    started: datetime,
    stream: str,
    event_type: str,
    summary: str,
    source_mode: str,
    source_ref: str | None,
    delay_seconds: float,
    sleep_seconds: float,
) -> dict[str, Any]:
    elapsed_ms = max(0, int(round((timestamp - started).total_seconds() * 1000)))
    event = {
        "schema_version": TIMELINE_EVENT_SCHEMA_VERSION,
        "type": "timeline_event",
        "sequence": sequence,
        "timestamp": _isoformat(timestamp),
        "elapsed_ms": elapsed_ms,
        "stream": stream,
        "event_type": event_type,
        "summary": summary,
        "source_mode": source_mode,
        "source_ref": source_ref,
        "delay_seconds": round(delay_seconds, 3),
        "sleep_seconds": sleep_seconds,
        "redacted": True,
        "hidden_answer_material_visible": False,
    }
    event["line"] = _format_line(event)
    return event


def _format_line(event: Mapping[str, Any]) -> str:
    elapsed = _format_elapsed_ms(_int(event.get("elapsed_ms"), default=0))
    stream = _safe_token(event.get("stream") or "agent")
    event_type = _safe_token(event.get("event_type") or "event")
    summary = _safe_text(event.get("summary") or "")
    if stream == "logs":
        return f"{elapsed} [logs] {summary}"
    if stream == "metrics":
        return f"{elapsed} [metrics] {summary}"
    if stream == "traffic":
        return f"{elapsed} [traffic] {summary}"
    if stream == "inspect":
        return f"{elapsed} [inspect] {summary}"
    if stream == "evidence":
        return f"{elapsed} [evidence] {summary}"
    if stream == "action":
        return f"{elapsed} [action] {summary}"
    if stream == "gate":
        return f"{elapsed} [gate] {summary}"
    if stream == "judge":
        return f"{elapsed} [judge] {summary}"
    if stream == "gap":
        return f"{elapsed} [gap] {summary}"
    return f"{elapsed} [{stream}] {event_type}: {summary}"


def _raw_event(
    generated_at: str,
    offset_ms: int,
    stream: str,
    event_type: str,
    summary: str,
    source_ref: str,
    sequence: int,
) -> dict[str, Any]:
    timestamp = _parse_timestamp(generated_at) + timedelta(milliseconds=offset_ms)
    return {
        "timestamp": timestamp,
        "stream": stream,
        "event_type": event_type,
        "summary": _safe_text(summary),
        "source_ref": source_ref,
        "source_path": source_ref,
        "source_sequence": sequence,
        "redacted": True,
    }


def _raw_event_at(
    timestamp: datetime,
    stream: str,
    event_type: str,
    summary: str,
    source_ref: str,
    sequence: int,
) -> dict[str, Any]:
    return {
        "timestamp": timestamp,
        "stream": _stream(stream, default="agent"),
        "event_type": _safe_token(event_type or "event"),
        "summary": _safe_text(summary),
        "source_ref": source_ref,
        "source_path": source_ref,
        "source_sequence": sequence,
        "redacted": True,
    }


def _raw_event_at_elapsed(
    generated_at: str,
    elapsed_ms: int,
    stream: str,
    event_type: str,
    summary: str,
    source_ref: str,
    sequence: int,
) -> dict[str, Any]:
    timestamp = _parse_timestamp(generated_at) + timedelta(milliseconds=max(0, elapsed_ms))
    return _raw_event_at(timestamp, stream, event_type, summary, source_ref, sequence)


def _raw_event_after(
    events: list[dict[str, Any]],
    generated_at: str,
    stream: str,
    event_type: str,
    summary: str,
    source_ref: str,
) -> dict[str, Any]:
    previous = max((event["timestamp"] for event in events), default=_parse_timestamp(generated_at))
    return _raw_event_at(
        previous + timedelta(seconds=1),
        stream,
        event_type,
        summary,
        source_ref,
        len(events) + 1,
    )


def _load_json_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ExperienceError(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise ExperienceError(f"{label} must contain a JSON object")
    return payload


def _load_ndjson(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ExperienceError(f"{path}:{line_no} is not valid JSON: {exc}") from exc
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _load_ndjson_for_follow(path: Path) -> list[dict[str, Any]]:
    content = path.read_text(encoding="utf-8")
    lines = content.splitlines()
    complete = content.endswith("\n")
    rows: list[dict[str, Any]] = []
    for index, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            if not complete and index == len(lines):
                break
            raise ExperienceError(f"{path}:{index} is not valid JSON: {exc}") from exc
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _follow_payload(
    artifact_dir: Path,
    *,
    generated_at: str,
    timeline: list[dict[str, Any]],
    state: str,
    speed: float,
    max_gap_seconds: float,
    poll_interval_seconds: float,
    timeout_seconds: float | None,
    idle_timeout_seconds: float | None,
    fallback_replay: bool,
) -> dict[str, Any]:
    stream_counts = Counter(event["stream"] for event in timeline)
    return {
        "schema_version": EXPERIENCE_SCHEMA_VERSION,
        "mode": "follow",
        "source_mode": EVENTS_SOURCE_MODE,
        "artifact_dir": str(artifact_dir),
        "generated_at": generated_at,
        "event_count": len(timeline),
        "stream_counts": dict(sorted(stream_counts.items())),
        "options": {
            "speed": speed,
            "max_gap_seconds": max_gap_seconds,
            "poll_interval_seconds": poll_interval_seconds,
            "timeout_seconds": timeout_seconds,
            "idle_timeout_seconds": idle_timeout_seconds,
        },
        "follow": {
            "state": state,
            "events_path": _relative(artifact_dir / "events.ndjson", artifact_dir),
            "fallback_replay": fallback_replay,
        },
        "artifacts": {
            "experience": "experience.json",
            "timeline": "timeline.ndjson",
        },
    }


def _follow_is_complete(artifact_dir: Path, rows: list[Mapping[str, Any]]) -> bool:
    if _terminal_dashboard_status(artifact_dir / "dashboard.json"):
        return True
    if (artifact_dir / "summary.json").is_file() or (artifact_dir / "result.json").is_file():
        return True
    for row in reversed(rows):
        phase = _safe_token(row.get("phase") or row.get("event") or row.get("event_type") or "")
        status = _safe_token(row.get("status") or row.get("state") or "")
        if phase in {"run", "batch"} and status in FOLLOW_TERMINAL_STATUSES:
            return True
        if phase == "case_result" and status in {"passed", "failed", "blocked", "error"}:
            return True
    return False


def _terminal_dashboard_status(path: Path) -> bool:
    if not path.is_file():
        return False
    try:
        payload = _load_json_object(path, label="dashboard.json")
    except (OSError, json.JSONDecodeError, ExperienceError):
        return False
    status = _safe_token(payload.get("status") or "")
    return status in FOLLOW_TERMINAL_STATUSES


def _has_post_run_replay_artifact(artifact_dir: Path) -> bool:
    return any(
        path.is_file()
        for path in [
            artifact_dir / "investigation-transcript.ndjson",
            artifact_dir / "trace.json",
            artifact_dir / "dashboard.json",
            artifact_dir / "result.json",
        ]
    ) or any(artifact_dir.glob("cases/*/investigation-transcript.ndjson"))


def _timestamp_for(row: Mapping[str, Any], *, generated_at: str, fallback_offset_ms: int) -> datetime:
    timestamp = _parse_optional_timestamp(row.get("timestamp"))
    if timestamp is not None:
        return timestamp
    elapsed_ms = row.get("elapsed_ms")
    if isinstance(elapsed_ms, (int, float)):
        return _parse_timestamp(generated_at) + timedelta(milliseconds=max(0, int(elapsed_ms)))
    return _parse_timestamp(generated_at) + timedelta(milliseconds=fallback_offset_ms)


def _parse_optional_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return _parse_timestamp(value)
    except ValueError:
        return None


def _parse_timestamp(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _isoformat(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _utc_now() -> str:
    return _isoformat(datetime.now(timezone.utc))


def _stream(value: Any, *, default: str) -> str:
    text = _safe_token(value)
    if text in STREAMS:
        return text
    if text in {"selector", "seed", "port_forward", "archetype", "validate", "fixture"}:
        return "inspect"
    if text in {"wait", "wait_for", "observe", "observation"}:
        return "evidence"
    return default


def _dashboard_phase_stream(phase: str, status: str) -> str:
    if phase in {"seed", "selector", "port_forward", "providers", "archetype", "validate", "fixture"}:
        return "inspect"
    if phase in {"wait", "wait_for", "observe", "observation"}:
        return "evidence"
    if phase in {"teardown", "warm_kind_cleanup", "run"} and status in {"ok", "blocked", "failed", "error"}:
        return "gate"
    if phase in {"hold", "loadgen", "traffic"}:
        return "traffic"
    return "inspect"


def _dashboard_signal_stream(signal: str, source: str, detail: str) -> str:
    text = _safe_token(" ".join([signal, source, detail]))
    if any(token in text for token in ("log", "journal", "stderr", "stdout", "gc_")):
        return "logs"
    if any(token in text for token in ("http", "traffic", "request", "route", "endpoint", "dns", "tls")):
        return "traffic"
    if any(
        token in text
        for token in (
            "metric",
            "container",
            "image",
            "pod",
            "cpu",
            "memory",
            "latency",
            "error_rate",
            "pool",
            "saturation",
            "prometheus",
            "result",
        )
    ):
        return "metrics"
    if any(token in text for token in ("seed", "teardown", "provider", "deploy")):
        return "inspect"
    return "evidence"


def _noise_profile_stream(noise_profile: str) -> str:
    token = _safe_token(noise_profile)
    if any(value in token for value in ("api", "client", "edge", "http")):
        return "traffic"
    if any(value in token for value in ("runtime", "log")):
        return "logs"
    return "metrics"


def _first_hypothesis_summary(response: Mapping[str, Any]) -> str:
    hypotheses = response.get("hypotheses_ranked")
    if not isinstance(hypotheses, list) or not hypotheses:
        return _safe_text(response.get("summary") or "agent response retained")
    first = hypotheses[0]
    if not isinstance(first, Mapping):
        return "agent response retained"
    return _safe_text(first.get("summary") or first.get("hypothesis") or first.get("id") or "agent response retained")


def _source_ref(raw: Mapping[str, Any]) -> str:
    source_ref = raw.get("source_ref")
    if isinstance(source_ref, str) and source_ref:
        return source_ref
    source_path = raw.get("source_path")
    if isinstance(source_path, str) and source_path:
        return source_path
    return "artifact"


def _compact_event_name(phase: str, status: str) -> str:
    return status and f"{phase} {status}" or phase


def _safe_text(value: Any, *, limit: int = 240) -> str:
    text = str(value if value is not None else "")
    text = _redact_hidden_answer_fields(redact(text))
    text = " ".join(text.split())
    return text[: limit - 3] + "..." if len(text) > limit else text


def _safe_token(value: Any) -> str:
    text = _safe_text(value, limit=80).lower().replace("-", "_")
    cleaned = "".join(ch for ch in text if ch.isalnum() or ch in "._")
    return cleaned if cleaned.strip("._") else ""


def _string(value: Any) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _redact_hidden_answer_fields(text: str) -> str:
    redacted = text
    for field in sorted(HIDDEN_ANSWER_FIELDS):
        for spelling in {field, field.replace("_", "-")}:
            redacted = re.sub(
                rf"\b{re.escape(spelling)}\b\s*[:=]\s*[^,;\n ]+",
                "[hidden-answer-field]",
                redacted,
                flags=re.IGNORECASE,
            )
            redacted = re.sub(re.escape(spelling), "[hidden-answer-field]", redacted, flags=re.IGNORECASE)
    return redacted


def _relative(path: Path, root: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _format_elapsed_ms(elapsed_ms: int) -> str:
    seconds = elapsed_ms / 1000.0
    return f"+{seconds:08.3f}s"


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, remainder = divmod(int(round(seconds)), 60)
    if minutes < 60:
        return f"{minutes}m{remainder:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def _elapsed_to_ms(value: Any, *, default: int) -> int:
    if isinstance(value, (int, float)):
        return max(0, int(value))
    if not isinstance(value, str):
        return default
    text = value.strip()
    if not text:
        return default
    if text.endswith("ms"):
        try:
            return max(0, int(float(text[:-2])))
        except ValueError:
            return default
    if text.endswith("s") and re.fullmatch(r"\d+(?:\.\d+)?s", text):
        return max(0, int(float(text[:-1]) * 1000))
    match = re.fullmatch(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?", text)
    if match and any(group is not None for group in match.groups()):
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2) or 0)
        seconds = float(match.group(3) or 0)
        return max(0, int((hours * 3600 + minutes * 60 + seconds) * 1000))
    if ":" in text:
        parts = text.split(":")
        try:
            numbers = [int(part) for part in parts]
        except ValueError:
            return default
        if len(numbers) == 2:
            minutes, seconds = numbers
            return max(0, (minutes * 60 + seconds) * 1000)
        if len(numbers) == 3:
            hours, minutes, seconds = numbers
            return max(0, (hours * 3600 + minutes * 60 + seconds) * 1000)
    try:
        return max(0, int(float(text) * 1000))
    except ValueError:
        return default


def _int(value: Any, *, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
