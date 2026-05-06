"""Benchmark runner support for external agent adapter exchanges."""

from __future__ import annotations

import json
import shlex
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


DEFAULT_AGENT_ADAPTER_EXCHANGE_RELATIVE = Path("harness/agent-adapter-contract-example.json")
RESULT_SCHEMA_VERSION = "incident-generator.benchmark-result/v1"


class BenchmarkRunnerError(ValueError):
    """Raised when a benchmark runner input cannot produce a result payload."""


def run_agent_adapter_benchmark(
    root: Path,
    *,
    exchange_path: Path = DEFAULT_AGENT_ADAPTER_EXCHANGE_RELATIVE,
    adapter_command: str | None = None,
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
) -> dict[str, Any]:
    """Run or replay one adapter exchange and emit a benchmark-result payload."""

    expected_hypotheses = _unique_strings(expected_hypotheses)
    forbidden_hypotheses = _unique_strings(forbidden_hypotheses or [])
    false_attribution_guards = _unique_strings(false_attribution_guards or [])
    resolved_exchange_path = _resolve_path(root, exchange_path)
    exchange = _load_json_object(resolved_exchange_path)
    request = _object_field(exchange, "request")
    fixture_response = _object_field(exchange, "response")
    response, adapter_error, measured_duration_ms = _response_for_exchange(
        request,
        fixture_response,
        adapter_command=adapter_command,
    )
    return build_benchmark_result(
        root,
        exchange_path=resolved_exchange_path,
        exchange=exchange,
        response=response,
        adapter_command=adapter_command,
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
    )


def build_benchmark_result(
    root: Path,
    *,
    exchange_path: Path,
    exchange: Mapping[str, Any],
    response: Mapping[str, Any],
    adapter_command: str | None,
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
                    "artifact_refs": [exchange_ref],
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
                "judge": {
                    "judge_kind": "none",
                    "model": None,
                    "separate_family_required": False,
                },
                "command_ref": adapter_command or _relative_path(root, exchange_path),
            }
        ],
        "results": [result],
        "aggregate": _aggregate([result], required_abstention=required_abstention, uncertainty_expected=uncertainty_expected),
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
        "scoring": {
            "hypothesis_pass": hypothesis_pass,
            "evidence_reference_pass": evidence_reference_pass,
            "abstention_pass": abstention_pass,
            "uncertainty_pass": uncertainty_pass,
            "false_attribution_pass": false_attribution_pass,
            "overall_pass": overall_pass,
        },
        "judge_outcome": {
            "status": "not_requested",
            "judge_kind": "none",
            "verdict": "not_applicable",
            "score": None,
            "model": None,
            "separate_family_ok": None,
            "rationale_ref": None,
            "failure_reason": None,
        },
        "failure_class": failure_class,
        "notes": adapter_error if adapter_error is not None else "adapter response mapped without an external judge",
    }


def _aggregate(
    results: list[Mapping[str, Any]],
    *,
    required_abstention: bool,
    uncertainty_expected: bool,
) -> dict[str, int]:
    return {
        "case_count": 1,
        "entrant_count": 1,
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
        "required_abstentions": 1 if required_abstention else 0,
        "abstentions_observed": sum(
            1 for result in results if result.get("evidence_discipline", {}).get("abstained") is True
        ),
        "uncertainty_required_count": 1 if uncertainty_expected else 0,
        "uncertainty_observed_count": sum(
            1 for result in results if result.get("evidence_discipline", {}).get("uncertainty_stated") is True
        ),
        "judge_executed_count": 0,
        "judge_passed_count": 0,
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
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise BenchmarkRunnerError(f"expected JSON object in {path}")
    return payload


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


def _relative_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
