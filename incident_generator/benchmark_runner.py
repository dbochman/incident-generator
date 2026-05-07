"""Benchmark runner support for external agent adapter exchanges."""

from __future__ import annotations

import json
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any, Mapping

from .benchmark_result_helpers import (
    load_json_object as _shared_load_json_object,
    sha256_file as _sha256_file,
    utc_now as _utc_now,
    write_json_file as _write_json_file,
)
from .parsers import load_yaml


DEFAULT_AGENT_ADAPTER_EXCHANGE_RELATIVE = Path("harness/agent-adapter-contract-example.json")
DEFAULT_AGENT_ADAPTER_BENCHMARK_SET_RELATIVE = Path("harness/agent-adapter-benchmark-set.yaml")
RESULT_SCHEMA_VERSION = "incident-generator.benchmark-result/v1"


class BenchmarkRunnerError(ValueError):
    """Raised when a benchmark runner input cannot produce a result payload."""


def run_agent_adapter_benchmark(
    root: Path,
    *,
    exchange_path: Path = DEFAULT_AGENT_ADAPTER_EXCHANGE_RELATIVE,
    adapter_command: str | None = None,
    judge_pack: Mapping[str, Any] | None = None,
    expected_hypotheses: list[str],
    forbidden_hypotheses: list[str] | None = None,
    false_attribution_guards: list[str] | None = None,
    evidence_role_expectations: list[dict[str, int | str]] | None = None,
    required_abstention: bool = False,
    uncertainty_expected: bool = False,
    scenario_ids: list[str] | None = None,
    archetype: str = "unknown",
    result_id: str | None = None,
    created_at: str | None = None,
    artifact_dir: Path | None = None,
) -> dict[str, Any]:
    """Run or replay one adapter exchange and emit a benchmark-result payload."""

    expected_hypotheses = _unique_strings(expected_hypotheses)
    forbidden_hypotheses = _unique_strings(forbidden_hypotheses or [])
    false_attribution_guards = _unique_strings(false_attribution_guards or [])
    payload, event = _run_agent_adapter_case(
        root,
        exchange_path=exchange_path,
        adapter_command=adapter_command,
        judge_pack=judge_pack,
        expected_hypotheses=expected_hypotheses,
        forbidden_hypotheses=forbidden_hypotheses,
        false_attribution_guards=false_attribution_guards,
        evidence_role_expectations=evidence_role_expectations or [],
        required_abstention=required_abstention,
        uncertainty_expected=uncertainty_expected,
        scenario_ids=scenario_ids,
        archetype=archetype,
        result_id=result_id,
        created_at=created_at,
        artifact_dir=artifact_dir,
    )
    if artifact_dir is not None:
        _write_run_artifacts(root, artifact_dir, payload, [event])
    return payload


def run_agent_adapter_benchmark_set(
    root: Path,
    *,
    benchmark_set_path: Path = DEFAULT_AGENT_ADAPTER_BENCHMARK_SET_RELATIVE,
    adapter_command: str | None = None,
    judge_pack: Mapping[str, Any] | None = None,
    result_id: str | None = None,
    created_at: str | None = None,
    artifact_dir: Path | None = None,
) -> dict[str, Any]:
    """Run or replay every adapter exchange in a checked benchmark-set manifest."""

    resolved_set_path = _resolve_path(root, benchmark_set_path)
    benchmark_set = load_yaml(resolved_set_path)
    case_specs = _benchmark_set_case_specs(benchmark_set)
    case_payloads: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    for case_spec in case_specs:
        payload, event = _run_agent_adapter_case(
            root,
            exchange_path=Path(case_spec["exchange"]),
            adapter_command=adapter_command,
            judge_pack=judge_pack,
            expected_hypotheses=case_spec["expected_hypotheses"],
            forbidden_hypotheses=case_spec["forbidden_hypotheses"],
            false_attribution_guards=case_spec["false_attribution_guards"],
            evidence_role_expectations=case_spec["evidence_role_expectations"],
            required_abstention=case_spec["required_abstention"],
            uncertainty_expected=case_spec["uncertainty_expected"],
            scenario_ids=case_spec["scenario_ids"],
            archetype=case_spec["archetype"],
            result_id=None,
            created_at=created_at,
            artifact_dir=artifact_dir,
        )
        case_payloads.append(payload)
        events.append(event)
    payload = _merge_benchmark_set_payloads(
        root,
        benchmark_set_path=resolved_set_path,
        benchmark_set=benchmark_set,
        case_payloads=case_payloads,
        result_id=result_id,
        created_at=created_at,
    )
    if artifact_dir is not None:
        _write_run_artifacts(root, artifact_dir, payload, events)
    return payload


def _run_agent_adapter_case(
    root: Path,
    *,
    exchange_path: Path,
    adapter_command: str | None,
    judge_pack: Mapping[str, Any] | None,
    expected_hypotheses: list[str],
    forbidden_hypotheses: list[str],
    false_attribution_guards: list[str],
    evidence_role_expectations: list[dict[str, int | str]],
    required_abstention: bool,
    uncertainty_expected: bool,
    scenario_ids: list[str] | None,
    archetype: str,
    result_id: str | None,
    created_at: str | None,
    artifact_dir: Path | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    resolved_exchange_path = _resolve_path(root, exchange_path)
    exchange = _load_json_object(resolved_exchange_path)
    request = _object_field(exchange, "request")
    fixture_response = _object_field(exchange, "response")
    response, adapter_error, measured_duration_ms = _response_for_exchange(
        request,
        fixture_response,
        adapter_command=adapter_command,
    )
    extra_artifact_refs: list[dict[str, str | None]] = []
    if artifact_dir is not None:
        response, extra_artifact_refs = _write_case_artifacts(
            root,
            artifact_dir,
            case_id=_required_string(request, "case_id"),
            request=request,
            response=response,
            adapter_error=adapter_error,
        )
    payload = build_benchmark_result(
        root,
        exchange_path=resolved_exchange_path,
        exchange=exchange,
        response=response,
        adapter_command=adapter_command,
        judge_pack=judge_pack,
        adapter_error=adapter_error,
        measured_duration_ms=measured_duration_ms,
        expected_hypotheses=expected_hypotheses,
        forbidden_hypotheses=forbidden_hypotheses,
        false_attribution_guards=false_attribution_guards,
        evidence_role_expectations=evidence_role_expectations or [],
        required_abstention=required_abstention,
        uncertainty_expected=uncertainty_expected,
        scenario_ids=scenario_ids,
        archetype=archetype,
        result_id=result_id,
        created_at=created_at,
        extra_artifact_refs=extra_artifact_refs,
    )
    result = payload["results"][0]
    return payload, {
        "schema_version": "incident-generator.benchmark-runner-event/v1",
        "event": "case_result",
        "case_id": result["case_id"],
        "entrant_id": result["entrant_id"],
        "state": result["state"],
        "failure_class": result["failure_class"],
        "duration_ms": result["duration_ms"],
        "adapter_error": adapter_error,
    }


def build_benchmark_result(
    root: Path,
    *,
    exchange_path: Path,
    exchange: Mapping[str, Any],
    response: Mapping[str, Any],
    adapter_command: str | None,
    judge_pack: Mapping[str, Any] | None,
    adapter_error: str | None,
    measured_duration_ms: int | None,
    expected_hypotheses: list[str],
    forbidden_hypotheses: list[str],
    false_attribution_guards: list[str],
    evidence_role_expectations: list[dict[str, int | str]],
    required_abstention: bool,
    uncertainty_expected: bool,
    scenario_ids: list[str] | None,
    archetype: str,
    result_id: str | None,
    created_at: str | None,
    extra_artifact_refs: list[dict[str, str | None]] | None = None,
) -> dict[str, Any]:
    request = _object_field(exchange, "request")
    benchmark_set_id = _required_string(request, "benchmark_set_id")
    case_id = _required_string(request, "case_id")
    incident_session_id = _required_string(request, "incident_session_id")
    collection_mode = request.get("collection_mode") if request.get("collection_mode") in {"fixture", "real"} else "fixture"
    response_agent = _object_field(response, "agent", default={})
    entrant_id = _required_string(response_agent, "adapter_id", default="external-agent")
    created = created_at or _utc_now()
    scenario_id_list = scenario_ids or [case_id]
    exchange_ref = _artifact_ref(root, exchange_path, notes="agent adapter exchange")
    artifact_refs = [exchange_ref, *(extra_artifact_refs or [])]

    result = _case_result(
        request,
        response,
        entrant_id=entrant_id,
        case_id=case_id,
        expected_hypotheses=expected_hypotheses,
        forbidden_hypotheses=forbidden_hypotheses,
        required_abstention=required_abstention,
        uncertainty_expected=uncertainty_expected,
        adapter_error=adapter_error,
        measured_duration_ms=measured_duration_ms,
        exchange_ref=exchange_ref["ref"],
        judge_pack=judge_pack,
    )
    state = result["state"]
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "result_id": result_id or f"{benchmark_set_id}-{case_id}-{entrant_id}",
        "benchmark_set": {
            "benchmark_set_id": benchmark_set_id,
            "name": f"External adapter benchmark: {benchmark_set_id}",
            "seed": None,
            "collection_modes": [collection_mode],
            "case_count": 1,
            "source_refs": [exchange_ref],
        },
        "created_at": created,
        "cases": [
            {
                "case_id": case_id,
                "generated_incident": {
                    "incident_run_id": incident_session_id,
                    "scenario_ids": scenario_id_list,
                    "combination_size": len(scenario_id_list),
                    "archetype": archetype,
                    "collection_mode": collection_mode,
                    "generation_state": "passed" if adapter_error is None else "partial",
                    "failure_class": "none" if adapter_error is None else "adapter_runtime_issue",
                    "artifact_refs": artifact_refs,
                },
                "expectations": {
                    "expected_hypotheses": expected_hypotheses,
                    "forbidden_hypotheses": forbidden_hypotheses,
                    "required_abstention": required_abstention,
                    "uncertainty_expected": uncertainty_expected,
                    "false_attribution_guards": false_attribution_guards,
                    "evidence_role_expectations": evidence_role_expectations,
                },
            }
        ],
        "entrants": [
            {
                "entrant_id": entrant_id,
                "display_name": _required_string(response_agent, "display_name", default=entrant_id),
                "agent_kind": "external",
                "execution_mode": response_agent.get("execution_mode", "offline"),
                "agent_version": response_agent.get("adapter_version"),
                "model": _result_model(response_agent.get("model"), fallback_id=entrant_id),
                "judge": _judge_config(judge_pack),
                "command_ref": adapter_command or _relative_path(root, exchange_path),
            }
        ],
        "results": [result],
        "aggregate": _aggregate(
            [result],
            cases=[
                {
                    "expectations": {
                        "required_abstention": required_abstention,
                        "uncertainty_expected": uncertainty_expected,
                    }
                }
            ],
        ),
        "notes": "Generated by incident_generator benchmark-runner from an external agent adapter exchange.",
    }


def parse_evidence_role_expectations(values: list[str] | None) -> list[dict[str, int | str]]:
    rows: list[dict[str, int | str]] = []
    for value in values or []:
        if "=" not in value:
            raise BenchmarkRunnerError(f"evidence role expectation must be ROLE=COUNT: {value}")
        role, count_text = value.split("=", 1)
        role = role.strip()
        count_text = count_text.strip()
        if role not in {"causal", "contextual", "ambient", "red_herring", "hostile"}:
            raise BenchmarkRunnerError(f"unsupported evidence role expectation: {role}")
        try:
            count = int(count_text)
        except ValueError as exc:
            raise BenchmarkRunnerError(f"invalid evidence role count for {role}: {count_text}") from exc
        if count < 0:
            raise BenchmarkRunnerError(f"evidence role count must be non-negative for {role}")
        rows.append({"role": role, "expected_count": count})
    return rows


def _benchmark_set_case_specs(benchmark_set: Mapping[str, Any]) -> list[dict[str, Any]]:
    cases = benchmark_set.get("cases")
    if not isinstance(cases, list) or not cases:
        raise BenchmarkRunnerError("benchmark set must contain at least one case")
    parsed: list[dict[str, Any]] = []
    seen_case_ids: set[str] = set()
    for index, item in enumerate(cases):
        if not isinstance(item, Mapping):
            raise BenchmarkRunnerError(f"benchmark set cases[{index}] must be an object")
        case_id = _required_string(item, "id", default=f"case-{index + 1}")
        if case_id in seen_case_ids:
            raise BenchmarkRunnerError(f"duplicate benchmark set case id: {case_id}")
        seen_case_ids.add(case_id)
        archetype = _string(item.get("archetype")) or "unknown"
        if archetype not in {"fixture", "kind", "linux-vm", "mixed", "unknown"}:
            raise BenchmarkRunnerError(f"unsupported benchmark set archetype for {case_id}: {archetype}")
        parsed.append(
            {
                "id": case_id,
                "exchange": _required_string(item, "exchange"),
                "expected_hypotheses": _string_list_field(item, "expected_hypotheses", required=True),
                "forbidden_hypotheses": _string_list_field(item, "forbidden_hypotheses"),
                "false_attribution_guards": _string_list_field(item, "false_attribution_guards"),
                "evidence_role_expectations": _evidence_role_expectation_field(
                    item.get("evidence_role_expectations", [])
                ),
                "required_abstention": _bool_field(item, "required_abstention", default=False),
                "uncertainty_expected": _bool_field(item, "uncertainty_expected", default=False),
                "scenario_ids": _optional_string_list_field(item, "scenario_ids"),
                "archetype": archetype,
            }
        )
    return parsed


def _merge_benchmark_set_payloads(
    root: Path,
    *,
    benchmark_set_path: Path,
    benchmark_set: Mapping[str, Any],
    case_payloads: list[dict[str, Any]],
    result_id: str | None,
    created_at: str | None,
) -> dict[str, Any]:
    if not case_payloads:
        raise BenchmarkRunnerError("benchmark set did not produce any case results")
    benchmark_set_id = _required_string(benchmark_set, "id")
    created = created_at or _utc_now()
    cases = [payload["cases"][0] for payload in case_payloads]
    results = [payload["results"][0] for payload in case_payloads]
    entrants = _unique_entrants(payload["entrants"][0] for payload in case_payloads)
    source_refs = _unique_artifact_refs(
        [
            _artifact_ref(root, benchmark_set_path, notes="agent adapter benchmark set"),
            *[
                source_ref
                for payload in case_payloads
                for source_ref in payload.get("benchmark_set", {}).get("source_refs", [])
                if isinstance(source_ref, Mapping)
            ],
        ]
    )
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "result_id": result_id or f"{benchmark_set_id}.{entrants[0]['entrant_id']}",
        "benchmark_set": {
            "benchmark_set_id": benchmark_set_id,
            "name": _string(benchmark_set.get("name")) or f"External adapter benchmark: {benchmark_set_id}",
            "seed": benchmark_set.get("seed") if isinstance(benchmark_set.get("seed"), int) else None,
            "collection_modes": _collection_modes(cases),
            "case_count": len(cases),
            "source_refs": source_refs,
        },
        "created_at": created,
        "cases": cases,
        "entrants": entrants,
        "results": results,
        "aggregate": _aggregate(results, cases=cases),
        "notes": _string(benchmark_set.get("description"))
        or "Generated by incident_generator benchmark-runner from a selected external adapter benchmark set.",
    }


def _write_case_artifacts(
    root: Path,
    artifact_dir: Path,
    *,
    case_id: str,
    request: Mapping[str, Any],
    response: Mapping[str, Any],
    adapter_error: str | None,
) -> tuple[Mapping[str, Any], list[dict[str, str | None]]]:
    case_dir = _artifact_root(root, artifact_dir) / "cases" / _safe_name(case_id)
    request_ref = _write_json_artifact(root, case_dir / "request.json", request, notes="redacted adapter request")
    response_ref = _write_json_artifact(root, case_dir / "response.json", response, notes="adapter response")
    refs = [request_ref, response_ref]
    if adapter_error is not None:
        refs.append(
            _write_json_artifact(
                root,
                case_dir / "adapter-error.json",
                {"error": adapter_error},
                notes="adapter command error",
            )
        )
    return _response_with_agent_output_ref(response, response_ref["ref"]), refs


def _write_run_artifacts(
    root: Path,
    artifact_dir: Path,
    payload: Mapping[str, Any],
    events: list[Mapping[str, Any]],
) -> None:
    artifact_root = _artifact_root(root, artifact_dir)
    _write_json_file(artifact_root / "result.json", payload)
    events_path = artifact_root / "events.ndjson"
    events_path.parent.mkdir(parents=True, exist_ok=True)
    events_path.write_text(
        "".join(json.dumps(event, sort_keys=True) + "\n" for event in events),
        encoding="utf-8",
    )
    _write_trace_artifacts(root, artifact_root, payload)
    _write_json_file(artifact_root / "summary.json", _artifact_summary(root, artifact_root, payload))


def _artifact_summary(root: Path, artifact_root: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    aggregate = payload.get("aggregate", {})
    benchmark_set = payload.get("benchmark_set", {})
    return {
        "schema_version": "incident-generator.benchmark-runner-summary/v1",
        "result_id": payload.get("result_id"),
        "benchmark_set_id": benchmark_set.get("benchmark_set_id") if isinstance(benchmark_set, Mapping) else None,
        "case_count": aggregate.get("case_count") if isinstance(aggregate, Mapping) else None,
        "result_count": aggregate.get("result_count") if isinstance(aggregate, Mapping) else None,
        "passed_count": aggregate.get("passed_count") if isinstance(aggregate, Mapping) else None,
        "failed_count": aggregate.get("failed_count") if isinstance(aggregate, Mapping) else None,
        "blocked_count": aggregate.get("blocked_count") if isinstance(aggregate, Mapping) else None,
        "artifacts": {
            "result": _relative_path(root, artifact_root / "result.json"),
            "summary": _relative_path(root, artifact_root / "summary.json"),
            "events": _relative_path(root, artifact_root / "events.ndjson"),
            "cases": _relative_path(root, artifact_root / "cases"),
            "trace": _relative_path(root, artifact_root / "trace.json"),
            "trace_markdown": _relative_path(root, artifact_root / "trace.md"),
        },
    }


def _write_trace_artifacts(root: Path, artifact_root: Path, payload: Mapping[str, Any]) -> None:
    trace = _build_trace_artifact(root, artifact_root, payload)
    _write_json_file(artifact_root / "trace.json", trace)
    trace_markdown = _render_trace_markdown(trace)
    (artifact_root / "trace.md").write_text(trace_markdown, encoding="utf-8")
    for case in trace["cases"]:
        case_dir = artifact_root / "cases" / _safe_name(str(case["case_id"]))
        case_dir.mkdir(parents=True, exist_ok=True)
        (case_dir / "transcript.md").write_text(_render_case_trace_markdown(case), encoding="utf-8")


def _build_trace_artifact(root: Path, artifact_root: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    benchmark_set = payload.get("benchmark_set") if isinstance(payload.get("benchmark_set"), Mapping) else {}
    results_by_case = {
        str(result.get("case_id")): result for result in payload.get("results", []) if isinstance(result, Mapping)
    }
    cases: list[dict[str, Any]] = []
    for case in payload.get("cases", []):
        if not isinstance(case, Mapping):
            continue
        case_id = _required_string(case, "case_id")
        case_dir = artifact_root / "cases" / _safe_name(case_id)
        request_path = case_dir / "request.json"
        response_path = case_dir / "response.json"
        request = _load_json_object(request_path) if request_path.is_file() else {}
        response = _load_json_object(response_path) if response_path.is_file() else {}
        result = results_by_case.get(case_id, {})
        cases.append(
            {
                "case_id": case_id,
                "state": result.get("state"),
                "request_ref": _relative_path(root, request_path),
                "response_ref": _relative_path(root, response_path),
                "transcript_ref": _relative_path(root, case_dir / "transcript.md"),
                "agent_prompt": _prompt_trace(request),
                "agent_response": _response_trace(response),
                "judge": {
                    "outcome": result.get("judge_outcome") if isinstance(result.get("judge_outcome"), Mapping) else {},
                    "scoring": result.get("scoring") if isinstance(result.get("scoring"), Mapping) else {},
                },
            }
        )
    return {
        "schema_version": "incident-generator.benchmark-runner-trace/v1",
        "result_id": payload.get("result_id"),
        "benchmark_set_id": benchmark_set.get("benchmark_set_id"),
        "case_count": len(cases),
        "cases": cases,
    }


def _prompt_trace(request: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": request.get("schema_version"),
        "request_id": request.get("request_id"),
        "case_id": request.get("case_id"),
        "incident_session_id": request.get("incident_session_id"),
        "input_mode": request.get("input_mode"),
        "skill_domains": request.get("skill_domains") if isinstance(request.get("skill_domains"), list) else [],
        "action_policy": request.get("action_policy") if isinstance(request.get("action_policy"), Mapping) else {},
        "output_contract": request.get("output_contract") if isinstance(request.get("output_contract"), Mapping) else {},
        "visibility": request.get("visibility") if isinstance(request.get("visibility"), Mapping) else {},
        "evidence_items": [_evidence_trace(item) for item in request.get("evidence_items", []) if isinstance(item, Mapping)],
    }


def _evidence_trace(item: Mapping[str, Any]) -> dict[str, Any]:
    content = item.get("content") if isinstance(item.get("content"), Mapping) else {}
    time_window = item.get("time_window") if isinstance(item.get("time_window"), Mapping) else {}
    return {
        "evidence_id": item.get("evidence_id"),
        "title": item.get("title"),
        "source_kind": item.get("source_kind"),
        "adapter_id": item.get("adapter_id"),
        "content_type": item.get("content_type"),
        "time_window": time_window,
        "redacted": item.get("redacted") is True,
        "untrusted": item.get("untrusted") is True,
        "excerpt": _excerpt(content.get("body") or content),
        "redaction_summary": content.get("redaction_summary"),
    }


def _response_trace(response: Mapping[str, Any]) -> dict[str, Any]:
    agent = response.get("agent") if isinstance(response.get("agent"), Mapping) else {}
    hypotheses = [
        {
            "rank": item.get("rank"),
            "summary": item.get("summary"),
            "confidence": item.get("confidence"),
            "evidence_refs": item.get("evidence_refs") if isinstance(item.get("evidence_refs"), list) else [],
            "missing_evidence": item.get("missing_evidence") if isinstance(item.get("missing_evidence"), list) else [],
        }
        for item in response.get("hypotheses_ranked", [])
        if isinstance(item, Mapping)
    ]
    return {
        "response_id": response.get("response_id"),
        "agent": {
            "adapter_id": agent.get("adapter_id"),
            "display_name": agent.get("display_name"),
            "execution_mode": agent.get("execution_mode"),
            "model": agent.get("model") if isinstance(agent.get("model"), Mapping) else None,
        },
        "duration_ms": response.get("duration_ms"),
        "primary_hypothesis_id": response.get("primary_hypothesis_id"),
        "hypotheses_ranked": hypotheses,
        "evidence_refs": response.get("evidence_refs") if isinstance(response.get("evidence_refs"), list) else [],
        "recommended_next_steps": response.get("recommended_next_steps")
        if isinstance(response.get("recommended_next_steps"), list)
        else [],
        "proposed_actions": response.get("proposed_actions") if isinstance(response.get("proposed_actions"), list) else [],
        "abstention": response.get("abstention") if isinstance(response.get("abstention"), Mapping) else {},
        "uncertainty": response.get("uncertainty") if isinstance(response.get("uncertainty"), Mapping) else {},
        "unsafe_actions_avoided": response.get("unsafe_actions_avoided")
        if isinstance(response.get("unsafe_actions_avoided"), list)
        else [],
    }


def _render_trace_markdown(trace: Mapping[str, Any]) -> str:
    lines = [
        "# Benchmark Runner Trace",
        "",
        f"Result: `{trace.get('result_id') or '-'}`",
        f"Benchmark set: `{trace.get('benchmark_set_id') or '-'}`",
        f"Cases: `{trace.get('case_count') or 0}`",
        "",
    ]
    for case in trace.get("cases", []):
        if isinstance(case, Mapping):
            lines.append(f"- [{case.get('case_id')}](cases/{_safe_name(str(case.get('case_id'))).strip()}/transcript.md): `{case.get('state') or '-'}`")
    return "\n".join(lines) + "\n"


def _render_case_trace_markdown(case: Mapping[str, Any]) -> str:
    prompt = case.get("agent_prompt") if isinstance(case.get("agent_prompt"), Mapping) else {}
    response = case.get("agent_response") if isinstance(case.get("agent_response"), Mapping) else {}
    judge = case.get("judge") if isinstance(case.get("judge"), Mapping) else {}
    outcome = judge.get("outcome") if isinstance(judge.get("outcome"), Mapping) else {}
    scoring = judge.get("scoring") if isinstance(judge.get("scoring"), Mapping) else {}
    agent = response.get("agent") if isinstance(response.get("agent"), Mapping) else {}
    lines = [
        f"# Adapter Case Trace: {case.get('case_id')}",
        "",
        "## Agent Prompt",
        "",
        f"- Request: `{prompt.get('request_id') or '-'}`",
        f"- Input mode: `{prompt.get('input_mode') or '-'}`",
        f"- Incident session: `{prompt.get('incident_session_id') or '-'}`",
        f"- Skill domains: `{', '.join(str(item) for item in prompt.get('skill_domains', [])) or '-'}`",
        f"- Expected answers visible: `{_visible_flag(prompt, 'expected_hypotheses_visible')}`",
        f"- Internal evidence roles visible: `{_visible_flag(prompt, 'internal_evidence_roles_visible')}`",
        "",
        "### Evidence Live Look",
        "",
        "| Evidence | Source | Type | Window | Redacted | Excerpt |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in prompt.get("evidence_items", []):
        if not isinstance(item, Mapping):
            continue
        time_window = item.get("time_window") if isinstance(item.get("time_window"), Mapping) else {}
        window = f"{time_window.get('start', '-') } to {time_window.get('end', '-')}"
        lines.append(
            "| {evidence} | {source} | {kind} | {window} | {redacted} | {excerpt} |".format(
                evidence=_md_text(item.get("title") or item.get("evidence_id") or "-"),
                source=_md_text(item.get("adapter_id") or item.get("source_kind") or "-"),
                kind=_md_text(item.get("content_type") or "-"),
                window=_md_text(window),
                redacted=_md_text(item.get("redacted")),
                excerpt=_md_text(item.get("excerpt") or "-"),
            )
        )
    lines.extend(
        [
            "",
            "## Agent Response",
            "",
            f"- Agent: `{agent.get('display_name') or agent.get('adapter_id') or '-'}`",
            f"- Execution mode: `{agent.get('execution_mode') or '-'}`",
            f"- Duration: `{response.get('duration_ms') or '-'}ms`",
            "",
            "| Rank | Hypothesis | Confidence | Evidence | Missing Evidence |",
            "| ---: | --- | --- | --- | --- |",
        ]
    )
    for item in response.get("hypotheses_ranked", []):
        if not isinstance(item, Mapping):
            continue
        lines.append(
            "| {rank} | {summary} | {confidence} | {evidence} | {missing} |".format(
                rank=_md_text(item.get("rank") or "-"),
                summary=_md_text(item.get("summary") or "-"),
                confidence=_md_text(item.get("confidence") or "-"),
                evidence=_md_text(", ".join(str(value) for value in item.get("evidence_refs", [])) or "-"),
                missing=_md_text(", ".join(str(value) for value in item.get("missing_evidence", [])) or "-"),
            )
        )
    lines.extend(
        [
            "",
            "## Judge Outcome",
            "",
            f"- Status: `{outcome.get('status') or '-'}`",
            f"- Judge kind: `{outcome.get('judge_kind') or '-'}`",
            f"- Verdict: `{outcome.get('verdict') or '-'}`",
            f"- Score: `{outcome.get('score') if outcome.get('score') is not None else '-'}`",
            f"- Failure reason: `{outcome.get('failure_reason') or '-'}`",
            "",
            "### Deterministic Checks",
            "",
            "| Check | Pass |",
            "| --- | --- |",
        ]
    )
    for key, value in scoring.items():
        lines.append(f"| {_md_text(key)} | {_md_text(value)} |")
    return "\n".join(lines) + "\n"


def _visible_flag(prompt: Mapping[str, Any], field: str) -> str:
    visibility = prompt.get("visibility") if isinstance(prompt.get("visibility"), Mapping) else {}
    value = visibility.get(field)
    return str(value) if isinstance(value, bool) else "-"


def _excerpt(value: Any, *, limit: int = 360) -> str:
    text = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
    text = " ".join(text.split())
    return text[: limit - 3] + "..." if len(text) > limit else text


def _md_text(value: Any) -> str:
    text = str(value if value is not None else "-")
    text = text.replace("|", "\\|").replace("\n", " ")
    return text[:237] + "..." if len(text) > 240 else text


def _write_json_artifact(root: Path, path: Path, payload: Mapping[str, Any], *, notes: str) -> dict[str, str | None]:
    _write_json_file(path, payload)
    return _artifact_ref(root, path, notes=notes)


def _response_with_agent_output_ref(response: Mapping[str, Any], ref: str | None) -> Mapping[str, Any]:
    if not ref:
        return response
    artifact_refs = [{"kind": "agent_output", "ref": ref, "sha256": None}]
    for item in response.get("artifact_refs", []):
        if isinstance(item, Mapping) and item.get("ref") != ref:
            artifact_refs.append(dict(item))
    enriched = dict(response)
    enriched["artifact_refs"] = artifact_refs
    return enriched


def _response_for_exchange(
    request: Mapping[str, Any],
    fixture_response: Mapping[str, Any],
    *,
    adapter_command: str | None,
) -> tuple[Mapping[str, Any], str | None, int | None]:
    if adapter_command is None:
        return fixture_response, None, None

    started = time.perf_counter()
    completed = subprocess.run(
        shlex.split(adapter_command),
        input=json.dumps(request, sort_keys=True),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    measured_duration_ms = max(0, int(round((time.perf_counter() - started) * 1000)))
    if completed.returncode != 0:
        return fixture_response, _adapter_error(completed, "adapter command failed"), measured_duration_ms
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return fixture_response, "adapter command did not emit valid JSON", measured_duration_ms
    if isinstance(payload, dict) and isinstance(payload.get("response"), dict):
        payload = payload["response"]
    if not isinstance(payload, dict):
        return fixture_response, "adapter command JSON output must be an object", measured_duration_ms
    return payload, None, measured_duration_ms


def _case_result(
    request: Mapping[str, Any],
    response: Mapping[str, Any],
    *,
    entrant_id: str,
    case_id: str,
    expected_hypotheses: list[str],
    forbidden_hypotheses: list[str],
    required_abstention: bool,
    uncertainty_expected: bool,
    adapter_error: str | None,
    measured_duration_ms: int | None,
    exchange_ref: str,
    judge_pack: Mapping[str, Any] | None,
) -> dict[str, Any]:
    hypotheses = [item for item in response.get("hypotheses_ranked", []) if isinstance(item, Mapping)]
    summaries = [_string(item.get("summary")) for item in hypotheses if _string(item.get("summary"))]
    matched = [expected for expected in expected_hypotheses if any(_matches_hypothesis(expected, summary) for summary in summaries)]
    missing = [expected for expected in expected_hypotheses if expected not in matched]
    unexpected = _unique_strings(
        [summary for summary in summaries if not any(_matches_hypothesis(expected, summary) for expected in expected_hypotheses)]
    )
    forbidden_observed = [
        forbidden
        for forbidden in forbidden_hypotheses
        if any(_matches_hypothesis(forbidden, summary) for summary in summaries)
    ]
    evidence_ids = _request_evidence_ids(request)
    cited_evidence = _response_evidence_ids(response)
    invalid_evidence_refs = [value for value in cited_evidence if value not in evidence_ids]
    abstention = response.get("abstention") if isinstance(response.get("abstention"), Mapping) else {}
    uncertainty = response.get("uncertainty") if isinstance(response.get("uncertainty"), Mapping) else {}
    abstained = abstention.get("abstained") if isinstance(abstention.get("abstained"), bool) else None
    uncertainty_stated = uncertainty.get("stated") if isinstance(uncertainty.get("stated"), bool) else None
    hypothesis_pass = not missing and not forbidden_observed and adapter_error is None
    evidence_reference_pass = bool(cited_evidence) and not invalid_evidence_refs and adapter_error is None
    abstention_pass = abstained is True if required_abstention else abstained is not True
    uncertainty_pass = uncertainty_stated is True if uncertainty_expected else True
    false_attribution_pass = not forbidden_observed and adapter_error is None
    overall_pass = all(
        [
            hypothesis_pass,
            evidence_reference_pass,
            abstention_pass,
            uncertainty_pass,
            false_attribution_pass,
        ]
    )
    response_state = response.get("state")
    if adapter_error is not None:
        state = "error"
        failure_class = "adapter_runtime_issue"
    elif response_state == "blocked":
        state = "blocked"
        failure_class = "adapter_runtime_issue"
    elif response_state == "error":
        state = "error"
        failure_class = "adapter_runtime_issue"
    else:
        state = "passed" if overall_pass else "failed"
        failure_class = "none" if overall_pass else "agent_hypothesis_regression"
    scoring = {
        "hypothesis_pass": hypothesis_pass,
        "evidence_reference_pass": evidence_reference_pass,
        "abstention_pass": abstention_pass,
        "uncertainty_pass": uncertainty_pass,
        "false_attribution_pass": false_attribution_pass,
        "overall_pass": overall_pass,
    }
    judge_outcome = _judge_outcome(judge_pack, scoring=scoring)
    if adapter_error is None and state not in {"blocked", "error"} and _judge_pack_blocks(judge_pack):
        state = "blocked"
        failure_class = "benchmark_runner_issue"
    primary = _primary_hypothesis_summary(response, hypotheses)
    duration = response.get("duration_ms")
    if not isinstance(duration, int):
        duration = measured_duration_ms
    return {
        "case_id": case_id,
        "entrant_id": entrant_id,
        "state": state,
        "duration_ms": duration,
        "agent_output_ref": _agent_output_ref(response) or exchange_ref,
        "diagnosis": {
            "primary_hypothesis": primary,
            "matched_expected_hypotheses": matched,
            "missing_expected_hypotheses": missing,
            "unexpected_hypotheses": unexpected,
            "evidence_refs": cited_evidence,
        },
        "evidence_discipline": {
            "abstention_required": required_abstention,
            "abstained": abstained,
            "uncertainty_required": uncertainty_expected,
            "uncertainty_stated": uncertainty_stated,
            "forbidden_hypotheses_observed": forbidden_observed,
            "false_attribution_observed": forbidden_observed,
            "hostile_instruction_followed": False,
        },
        "scoring": scoring,
        "judge_outcome": judge_outcome,
        "failure_class": failure_class,
        "notes": _case_notes(adapter_error=adapter_error, judge_pack=judge_pack),
    }


def _judge_config(judge_pack: Mapping[str, Any] | None) -> dict[str, Any]:
    if judge_pack is None:
        return {
            "judge_kind": "none",
            "model": None,
            "separate_family_required": False,
        }
    return {
        "judge_kind": _string(judge_pack.get("judge_kind")) or "none",
        "model": None,
        "separate_family_required": judge_pack.get("separate_family_required") is True,
    }


def _judge_outcome(judge_pack: Mapping[str, Any] | None, *, scoring: Mapping[str, Any]) -> dict[str, Any]:
    if judge_pack is None:
        return {
            "status": "not_requested",
            "judge_kind": "none",
            "verdict": "not_applicable",
            "score": None,
            "model": None,
            "separate_family_ok": None,
            "rationale_ref": None,
            "failure_reason": None,
        }
    judge_kind = _string(judge_pack.get("judge_kind")) or "none"
    if not _judge_pack_blocks(judge_pack):
        passed = scoring.get("overall_pass") is True
        return {
            "status": "executed",
            "judge_kind": judge_kind,
            "verdict": "pass" if passed else "fail",
            "score": 1.0 if passed else 0.0,
            "model": None,
            "separate_family_ok": None,
            "rationale_ref": None,
            "failure_reason": None if passed else "deterministic judge pack scoring failed",
        }
    return {
        "status": "blocked",
        "judge_kind": judge_kind,
        "verdict": "not_applicable",
        "score": None,
        "model": None,
        "separate_family_ok": None,
        "rationale_ref": None,
        "failure_reason": (
            f"judge pack {_string(judge_pack.get('id')) or judge_kind} requires live judge execution; "
            "benchmark-runner currently executes deterministic-local only"
        ),
    }


def _judge_pack_blocks(judge_pack: Mapping[str, Any] | None) -> bool:
    if judge_pack is None:
        return False
    return judge_pack.get("selection_status") != "executable" or judge_pack.get("judge_kind") != "deterministic"


def _case_notes(*, adapter_error: str | None, judge_pack: Mapping[str, Any] | None) -> str:
    if adapter_error is not None:
        return adapter_error
    if judge_pack is None:
        return "adapter response mapped without an external judge"
    if _judge_pack_blocks(judge_pack):
        return "adapter response mapped, but selected judge pack is blocked until live judge execution is implemented"
    return f"adapter response mapped with judge pack {_string(judge_pack.get('id')) or 'deterministic'}"


def _aggregate(
    results: list[Mapping[str, Any]],
    *,
    cases: list[Mapping[str, Any]],
) -> dict[str, int]:
    judge_outcomes = [
        result.get("judge_outcome") for result in results if isinstance(result.get("judge_outcome"), Mapping)
    ]
    return {
        "case_count": len(cases),
        "entrant_count": len({str(result.get("entrant_id")) for result in results if result.get("entrant_id")}),
        "result_count": len(results),
        "passed_count": sum(1 for result in results if result.get("state") == "passed"),
        "failed_count": sum(1 for result in results if result.get("state") == "failed"),
        "blocked_count": sum(1 for result in results if result.get("state") == "blocked"),
        "skipped_count": sum(1 for result in results if result.get("state") == "skipped"),
        "agent_hypothesis_regression_count": sum(
            1 for result in results if result.get("failure_class") == "agent_hypothesis_regression"
        ),
        "false_attribution_count": sum(
            1 for result in results if result.get("evidence_discipline", {}).get("false_attribution_observed")
        ),
        "required_abstentions": sum(
            1 for case in cases if case.get("expectations", {}).get("required_abstention") is True
        ),
        "abstentions_observed": sum(
            1 for result in results if result.get("evidence_discipline", {}).get("abstained") is True
        ),
        "uncertainty_required_count": sum(
            1 for case in cases if case.get("expectations", {}).get("uncertainty_expected") is True
        ),
        "uncertainty_observed_count": sum(
            1 for result in results if result.get("evidence_discipline", {}).get("uncertainty_stated") is True
        ),
        "judge_executed_count": sum(1 for outcome in judge_outcomes if outcome.get("status") == "executed"),
        "judge_passed_count": sum(
            1 for outcome in judge_outcomes if outcome.get("status") == "executed" and outcome.get("verdict") == "pass"
        ),
    }


def _request_evidence_ids(request: Mapping[str, Any]) -> set[str]:
    evidence_ids = set()
    for item in request.get("evidence_items", []):
        if isinstance(item, Mapping) and isinstance(item.get("evidence_id"), str):
            evidence_ids.add(item["evidence_id"])
    return evidence_ids


def _response_evidence_ids(response: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    for item in response.get("evidence_refs", []):
        if isinstance(item, Mapping):
            _append_unique(values, _string(item.get("evidence_id")))
    for hypothesis in response.get("hypotheses_ranked", []):
        if not isinstance(hypothesis, Mapping):
            continue
        for value in hypothesis.get("evidence_refs", []):
            _append_unique(values, _string(value))
    return values


def _primary_hypothesis_summary(response: Mapping[str, Any], hypotheses: list[Mapping[str, Any]]) -> str | None:
    primary_id = response.get("primary_hypothesis_id")
    for item in hypotheses:
        if item.get("hypothesis_id") == primary_id:
            return _string(item.get("summary")) or None
    if hypotheses:
        return _string(hypotheses[0].get("summary")) or None
    return None


def _agent_output_ref(response: Mapping[str, Any]) -> str | None:
    for item in response.get("artifact_refs", []):
        if isinstance(item, Mapping) and item.get("kind") == "agent_output" and isinstance(item.get("ref"), str):
            return item["ref"]
    return None


def _result_model(value: Any, *, fallback_id: str) -> dict[str, str] | None:
    if not isinstance(value, Mapping):
        return None
    return {
        "provider": _string(value.get("provider")) or "external",
        "model_id": _string(value.get("model_id")) or fallback_id,
        "model_family": _string(value.get("model_family")) or _string(value.get("provider")) or "external",
    }


def _artifact_ref(root: Path, path: Path, *, notes: str) -> dict[str, str | None]:
    return {
        "kind": "other",
        "ref": _relative_path(root, path),
        "sha256": _sha256_file(path),
        "notes": notes,
    }


def _adapter_error(completed: subprocess.CompletedProcess[str], fallback: str) -> str:
    detail = completed.stderr.strip() or completed.stdout.strip()
    if not detail:
        return fallback
    return f"{fallback}: {detail.splitlines()[0]}"


def _load_json_object(path: Path) -> dict[str, Any]:
    return _shared_load_json_object(
        path,
        error_cls=BenchmarkRunnerError,
        object_message="expected JSON object in {path}",
    )


def _object_field(mapping: Mapping[str, Any], key: str, *, default: Mapping[str, Any] | None = None) -> Mapping[str, Any]:
    value = mapping.get(key, default)
    if not isinstance(value, Mapping):
        raise BenchmarkRunnerError(f"expected object field {key}")
    return value


def _required_string(mapping: Mapping[str, Any], key: str, *, default: str | None = None) -> str:
    value = mapping.get(key, default)
    if not isinstance(value, str) or not value:
        raise BenchmarkRunnerError(f"expected non-empty string field {key}")
    return value


def _string_list_field(mapping: Mapping[str, Any], key: str, *, required: bool = False) -> list[str]:
    value = mapping.get(key, [])
    if required and not value:
        raise BenchmarkRunnerError(f"expected non-empty list field {key}")
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise BenchmarkRunnerError(f"expected string list field {key}")
    return _unique_strings(value)


def _optional_string_list_field(mapping: Mapping[str, Any], key: str) -> list[str] | None:
    if key not in mapping:
        return None
    return _string_list_field(mapping, key)


def _bool_field(mapping: Mapping[str, Any], key: str, *, default: bool) -> bool:
    value = mapping.get(key, default)
    if not isinstance(value, bool):
        raise BenchmarkRunnerError(f"expected boolean field {key}")
    return value


def _evidence_role_expectation_field(value: Any) -> list[dict[str, int | str]]:
    if not isinstance(value, list):
        raise BenchmarkRunnerError("evidence_role_expectations must be a list")
    if all(isinstance(item, str) for item in value):
        return parse_evidence_role_expectations(value)
    rows: list[dict[str, int | str]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise BenchmarkRunnerError("evidence_role_expectations items must be objects or ROLE=COUNT strings")
        role = item.get("role")
        count = item.get("expected_count")
        if not isinstance(role, str) or role not in {"causal", "contextual", "ambient", "red_herring", "hostile"}:
            raise BenchmarkRunnerError(f"unsupported evidence role expectation: {role}")
        if not isinstance(count, int) or count < 0:
            raise BenchmarkRunnerError(f"invalid evidence role count for {role}: {count}")
        rows.append({"role": role, "expected_count": count})
    return rows


def _unique_entrants(entrants: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for entrant in entrants:
        if not isinstance(entrant, Mapping):
            continue
        entrant_id = _string(entrant.get("entrant_id"))
        if not entrant_id or entrant_id in seen:
            continue
        seen.add(entrant_id)
        rows.append(dict(entrant))
    if not rows:
        raise BenchmarkRunnerError("benchmark set did not produce entrant metadata")
    return rows


def _unique_artifact_refs(refs: list[Mapping[str, Any]]) -> list[dict[str, str | None]]:
    rows: list[dict[str, str | None]] = []
    seen: set[str] = set()
    for ref in refs:
        ref_value = _string(ref.get("ref"))
        if not ref_value or ref_value in seen:
            continue
        seen.add(ref_value)
        row = {
            "kind": _string(ref.get("kind")) or "other",
            "ref": ref_value,
            "sha256": ref.get("sha256") if isinstance(ref.get("sha256"), str) else None,
        }
        notes = _string(ref.get("notes"))
        if notes:
            row["notes"] = notes
        rows.append(row)
    return rows


def _collection_modes(cases: list[Mapping[str, Any]]) -> list[str]:
    modes: list[str] = []
    for case in cases:
        incident = case.get("generated_incident")
        if isinstance(incident, Mapping):
            mode = _string(incident.get("collection_mode"))
            if mode in {"fixture", "real"}:
                _append_unique(modes, mode)
    return modes or ["fixture"]


def _matches_hypothesis(expected: str, summary: str) -> bool:
    normalized_expected = _normalize(expected)
    normalized_summary = _normalize(summary)
    return normalized_expected == normalized_summary or normalized_expected in normalized_summary


def _normalize(value: str) -> str:
    return " ".join(value.lower().split())


def _append_unique(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


def _unique_strings(values: list[str]) -> list[str]:
    unique: list[str] = []
    for value in values:
        _append_unique(unique, value)
    return unique


def _string(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _resolve_path(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _artifact_root(root: Path, artifact_dir: Path) -> Path:
    return artifact_dir if artifact_dir.is_absolute() else root / artifact_dir


def _relative_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _safe_name(value: str) -> str:
    safe = "".join(char if char.isalnum() or char in {"-", "_", "."} else "-" for char in value.strip())
    return safe.strip(".-") or "case"
