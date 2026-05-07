"""Benchmark-result payloads for recorded benchmark-combo LLM smoke snapshots."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .benchmark_result_helpers import (
    append_unique as _append_unique,
    artifact_ref as _artifact_ref,
    load_json_object,
    mapping as _mapping,
    resolve_path as _resolve_path,
    string as _string,
    string_list as _string_list,
    unique_refs as _unique_refs,
    utc_now as _utc_now,
)
from .scenarios import load_scenario_package


RESULT_SCHEMA_VERSION = "incident-generator.benchmark-result/v1"
LLM_SMOKE_SUMMARY_SCHEMA_VERSION = "incident-generator.llm-smoke-summary/v1"
DEFAULT_LLM_SMOKE_COMBO_PLAN_RELATIVE = Path("harness/benchmark-combo-llm-smoke.yaml")
DEFAULT_LLM_SMOKE_FIXTURE_SUMMARY_RELATIVE = Path("harness/benchmark-combo-llm-smoke-fixture-summary.json")
DEFAULT_LLM_SMOKE_LIVE_SUMMARY_RELATIVE = Path("harness/benchmark-combo-llm-smoke-live-summary.json")
DEFAULT_LLM_SMOKE_FIXTURE_SNAPSHOT_RELATIVE = DEFAULT_LLM_SMOKE_FIXTURE_SUMMARY_RELATIVE
DEFAULT_LLM_SMOKE_LIVE_SNAPSHOT_RELATIVE = DEFAULT_LLM_SMOKE_LIVE_SUMMARY_RELATIVE
DEFAULT_LLM_SMOKE_RESULT_BENCHMARK_SET_ID = "benchmark-combo-llm-smoke-20260506"


class LLMSmokeResultError(ValueError):
    """Raised when recorded LLM smoke snapshots cannot be mapped."""


def render_llm_smoke_result(
    root: Path,
    *,
    combo_plan_path: Path = DEFAULT_LLM_SMOKE_COMBO_PLAN_RELATIVE,
    fixture_snapshot_path: Path | None = None,
    live_snapshot_path: Path | None = None,
    fixture_summary_path: Path | None = None,
    live_summary_path: Path | None = None,
    mode: str | None = None,
    include_fixture: bool = True,
    include_live: bool = True,
    benchmark_set_id: str | None = None,
    name: str | None = None,
    result_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Render recorded fixture/live LLM smoke snapshots as benchmark results."""

    if mode is not None:
        if mode not in {"fixture", "live", "both"}:
            raise LLMSmokeResultError(f"unsupported LLM smoke result mode: {mode}")
        include_fixture = mode in {"fixture", "both"}
        include_live = mode in {"live", "both"}
    fixture_path = fixture_snapshot_path or fixture_summary_path or DEFAULT_LLM_SMOKE_FIXTURE_SNAPSHOT_RELATIVE
    live_path = live_snapshot_path or live_summary_path or DEFAULT_LLM_SMOKE_LIVE_SNAPSHOT_RELATIVE
    include_label = "both" if include_fixture and include_live else "fixture" if include_fixture else "live"
    summaries = _selected_summaries(
        root,
        include_fixture=include_fixture,
        include_live=include_live,
        fixture_snapshot_path=fixture_path,
        live_snapshot_path=live_path,
    )
    if not summaries:
        raise LLMSmokeResultError("at least one LLM smoke summary is required")

    set_id = benchmark_set_id or _benchmark_set_id(summaries[0][1])
    case_order, case_by_id = _cases(root, summaries)
    entrants = [_entrant(summary) for _, summary in summaries]
    results = [
        _result(root, summary, combo, case_id=_string(combo.get("combo_id")))
        for _, summary in summaries
        for combo in _combos(summary)
    ]
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "result_id": result_id or f"{set_id}.llm-smoke.{include_label}",
        "benchmark_set": {
            "benchmark_set_id": set_id,
            "name": name or f"LLM smoke results for {set_id}",
            "seed": _seed(summaries),
            "collection_modes": _collection_modes(summaries),
            "case_count": len(case_order),
            "source_refs": _source_refs(root, summaries, combo_plan_path=combo_plan_path),
        },
        "created_at": created_at or _utc_now(),
        "cases": [case_by_id[case_id] for case_id in case_order],
        "entrants": entrants,
        "results": results,
        "aggregate": _aggregate(results, cases=[case_by_id[case_id] for case_id in case_order], entrant_count=len(entrants)),
        "notes": _notes(summaries),
    }


def _selected_summaries(
    root: Path,
    *,
    include_fixture: bool,
    include_live: bool,
    fixture_snapshot_path: Path,
    live_snapshot_path: Path,
) -> list[tuple[Path, Mapping[str, Any]]]:
    selected: list[Path] = []
    if include_fixture:
        selected.append(fixture_snapshot_path)
    if include_live:
        selected.append(live_snapshot_path)
    if not selected:
        raise LLMSmokeResultError("at least one of include_fixture or include_live must be true")

    summaries: list[tuple[Path, Mapping[str, Any]]] = []
    seen_entrants: set[str] = set()
    for path in selected:
        resolved = _resolve_path(root, path)
        summary = load_json_object(resolved, error_cls=LLMSmokeResultError)
        _validate_summary(summary, resolved)
        entrant_id = _entrant_id(summary)
        if entrant_id in seen_entrants:
            raise LLMSmokeResultError(f"duplicate LLM smoke entrant_id: {entrant_id}")
        seen_entrants.add(entrant_id)
        summaries.append((resolved, summary))
    return summaries


def _validate_summary(summary: Mapping[str, Any], path: Path) -> None:
    if summary.get("schema_version") != LLM_SMOKE_SUMMARY_SCHEMA_VERSION:
        raise LLMSmokeResultError(f"unsupported LLM smoke summary schema_version in {path}: {summary.get('schema_version')}")
    if not _string(summary.get("benchmark_set_id")):
        raise LLMSmokeResultError(f"{path} missing benchmark_set_id")
    entrant = summary.get("entrant")
    if not isinstance(entrant, Mapping):
        raise LLMSmokeResultError(f"{path} missing entrant object")
    if _string(entrant.get("agent_kind")) not in {"fixture_llm", "live_llm"}:
        raise LLMSmokeResultError(f"{path} entrant agent_kind must be fixture_llm or live_llm")
    if not _combos(summary):
        raise LLMSmokeResultError(f"{path} contains no combos")


def _cases(root: Path, summaries: list[tuple[Path, Mapping[str, Any]]]) -> tuple[list[str], dict[str, dict[str, Any]]]:
    case_order: list[str] = []
    case_by_id: dict[str, dict[str, Any]] = {}
    for _, summary in summaries:
        for combo in _combos(summary):
            case_id = _string(combo.get("combo_id"))
            if not case_id:
                raise LLMSmokeResultError("LLM smoke combo missing combo_id")
            if case_id not in case_by_id:
                case_order.append(case_id)
                case_by_id[case_id] = _case(root, summary, combo)
            else:
                _assert_case_compatible(case_by_id[case_id], combo)
    return case_order, case_by_id


def _case(root: Path, summary: Mapping[str, Any], combo: Mapping[str, Any]) -> dict[str, Any]:
    scenario_ids = _string_list(combo.get("scenario_ids"))
    if not scenario_ids:
        raise LLMSmokeResultError(f"LLM smoke combo {_string(combo.get('combo_id'))} missing scenario_ids")
    return {
        "case_id": _string(combo.get("combo_id")),
        "generated_incident": {
            "incident_run_id": _string(combo.get("incident_run_id")) or None,
            "scenario_ids": scenario_ids,
            "combination_size": len(scenario_ids),
            "archetype": _archetype(summary),
            "collection_mode": _generated_collection_mode(summary),
            "generation_state": "passed" if combo.get("passed") is True else "failed",
            "failure_class": _failure_class(combo),
            "artifact_refs": _case_artifact_refs(root, summary, combo),
        },
        "expectations": {
            "expected_hypotheses": _string_list(combo.get("expected_hypotheses")),
            "forbidden_hypotheses": [],
            "required_abstention": False,
            "uncertainty_expected": False,
            "false_attribution_guards": [],
            "evidence_role_expectations": [],
        },
    }


def _assert_case_compatible(existing: Mapping[str, Any], combo: Mapping[str, Any]) -> None:
    incident = existing.get("generated_incident")
    if not isinstance(incident, Mapping):
        raise LLMSmokeResultError("existing case is malformed")
    if incident.get("scenario_ids") != _string_list(combo.get("scenario_ids")):
        raise LLMSmokeResultError(f"LLM smoke combo {_string(combo.get('combo_id'))} has inconsistent scenario_ids")


def _result(root: Path, summary: Mapping[str, Any], combo: Mapping[str, Any], *, case_id: str) -> dict[str, Any]:
    expected = _string_list(combo.get("expected_hypotheses"))
    observed = _string_list(combo.get("observed_hypotheses"))
    missing = [hypothesis for hypothesis in expected if hypothesis not in observed]
    matched = [hypothesis for hypothesis in expected if hypothesis in observed]
    unexpected = [hypothesis for hypothesis in observed if hypothesis not in expected]
    hypothesis_pass = not missing and combo.get("passed") is True
    evidence_refs = _evidence_refs(root, combo)
    tier2_status = _string(combo.get("tier2_status")) or "not_executed"
    judge_executed = tier2_status == "executed"
    overall_pass = hypothesis_pass and bool(evidence_refs) and judge_executed
    state = "passed" if overall_pass else "failed"
    return {
        "case_id": case_id,
        "entrant_id": _entrant_id(summary),
        "state": state,
        "duration_ms": _duration_ms(combo),
        "agent_output_ref": _agent_output_ref(summary, combo),
        "diagnosis": {
            "primary_hypothesis": observed[0] if observed else (expected[0] if expected else None),
            "matched_expected_hypotheses": matched,
            "missing_expected_hypotheses": missing,
            "unexpected_hypotheses": unexpected,
            "evidence_refs": evidence_refs,
        },
        "evidence_discipline": {
            "abstention_required": False,
            "abstained": False,
            "uncertainty_required": False,
            "uncertainty_stated": _uncertainty_stated(combo),
            "forbidden_hypotheses_observed": [],
            "false_attribution_observed": [],
            "hostile_instruction_followed": False,
        },
        "scoring": {
            "hypothesis_pass": hypothesis_pass,
            "evidence_reference_pass": bool(evidence_refs),
            "abstention_pass": True,
            "uncertainty_pass": True,
            "false_attribution_pass": True,
            "overall_pass": overall_pass,
        },
        "judge_outcome": _judge_outcome(summary, combo, overall_pass=overall_pass),
        "failure_class": "none" if overall_pass else _failure_class(combo, default="agent_hypothesis_regression"),
        "notes": f"{_string(summary.get('snapshot_id'))} {case_id}",
    }


def _entrant(summary: Mapping[str, Any]) -> dict[str, Any]:
    entrant = _mapping(summary.get("entrant"))
    judge = _mapping(entrant.get("judge"))
    return {
        "entrant_id": _entrant_id(summary),
        "display_name": _string(entrant.get("display_name")) or _entrant_id(summary),
        "agent_kind": _string(entrant.get("agent_kind")),
        "execution_mode": _string(entrant.get("execution_mode")),
        "agent_version": _string(entrant.get("agent_version")) or None,
        "model": _model_metadata(_mapping(entrant.get("model"))),
        "judge": {
            "judge_kind": _string(judge.get("judge_kind")) or "llm_tier2",
            "model": _model_metadata(judge),
            "separate_family_required": judge.get("separate_family_required") is not False,
        },
        "command_ref": _string(entrant.get("command_ref")) or None,
    }


def _judge_outcome(summary: Mapping[str, Any], combo: Mapping[str, Any], *, overall_pass: bool) -> dict[str, Any]:
    entrant = _mapping(summary.get("entrant"))
    judge = _mapping(entrant.get("judge"))
    executed = _string(combo.get("tier2_status")) == "executed"
    return {
        "status": "executed" if executed else "not_requested",
        "judge_kind": _string(judge.get("judge_kind")) or "llm_tier2",
        "verdict": "pass" if overall_pass else "fail",
        "score": 1.0 if overall_pass else 0.0,
        "model": _model_metadata(judge),
        "separate_family_ok": judge.get("separate_family_ok") if isinstance(judge.get("separate_family_ok"), bool) else None,
        "rationale_ref": _string(judge.get("rationale_ref")) or _agent_output_ref(summary, combo),
        "failure_reason": None if overall_pass else _failure_reason(combo),
    }


def _aggregate(results: list[Mapping[str, Any]], *, cases: list[Mapping[str, Any]], entrant_count: int) -> dict[str, int]:
    return {
        "case_count": len(cases),
        "entrant_count": entrant_count,
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
        "judge_executed_count": sum(
            1 for result in results if result.get("judge_outcome", {}).get("status") == "executed"
        ),
        "judge_passed_count": sum(
            1 for result in results if result.get("judge_outcome", {}).get("verdict") == "pass"
        ),
    }


def _source_refs(
    root: Path,
    summaries: list[tuple[Path, Mapping[str, Any]]],
    *,
    combo_plan_path: Path,
) -> list[dict[str, str | None]]:
    refs: list[dict[str, str | None]] = [
        _artifact_ref(root, _resolve_path(root, combo_plan_path), "harness_plan", notes="selected benchmark combo smoke plan")
    ]
    for summary_path, summary in summaries:
        for ref in _summary_source_refs(summary):
            refs.append(_artifact_ref(root, _resolve_path(root, Path(_string(ref.get("ref")))), _artifact_kind(ref), notes=_string(ref.get("notes"))))
        refs.append(_artifact_ref(root, summary_path, "llm_smoke", notes="checked LLM smoke summary snapshot"))
    return _unique_refs(refs)


def _case_artifact_refs(root: Path, summary: Mapping[str, Any], combo: Mapping[str, Any]) -> list[dict[str, str | None]]:
    refs: list[dict[str, str | None]] = []
    live_result = _string(combo.get("live_result_artifacts"))
    if live_result:
        refs.append(_artifact_ref(root, _resolve_path(root, Path(live_result)), "run_result", notes="validated warm-kind combo result"))
    replay = _string(combo.get("deterministic_agent_replay"))
    if replay:
        refs.append(_artifact_ref(root, _resolve_path(root, Path(replay)), "agent_replay", notes="validated deterministic combo replay"))
    summary_doc = _string(summary.get("summary_doc"))
    if summary_doc:
        refs.append(_artifact_ref(root, _resolve_path(root, Path(summary_doc)), "doc", notes="LLM smoke report"))
    return refs


def _summary_source_refs(summary: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    refs = summary.get("source_refs")
    return [ref for ref in refs if isinstance(ref, Mapping)] if isinstance(refs, list) else []


def _evidence_refs(root: Path, combo: Mapping[str, Any]) -> list[str]:
    refs: list[str] = []
    for raw_path in _string_list(combo.get("scenario_paths")):
        path = _resolve_path(root, Path(raw_path))
        try:
            package = load_scenario_package(path)
        except (OSError, ValueError):
            continue
        for adapter in _string_list(package.spec.get("evidence_adapters_required")):
            _append_unique(refs, adapter)
    if refs:
        return refs
    for row in _scenario_rows(combo):
        _append_unique(refs, _string(row.get("skill_name")))
    return refs


def _agent_output_ref(summary: Mapping[str, Any], combo: Mapping[str, Any]) -> str | None:
    doc = _string(summary.get("summary_doc"))
    case_id = _string(combo.get("combo_id"))
    return f"{doc}#{case_id}" if doc and case_id else doc or None


def _collection_modes(summaries: list[tuple[Path, Mapping[str, Any]]]) -> list[str]:
    modes: list[str] = []
    for _, summary in summaries:
        _append_unique(modes, _generated_collection_mode(summary))
        entrant = _mapping(summary.get("entrant"))
        execution_mode = _string(entrant.get("execution_mode"))
        if execution_mode == "fixture":
            _append_unique(modes, "fixture")
        elif execution_mode == "real":
            _append_unique(modes, "real")
    return [mode for mode in modes if mode in {"fixture", "real"}] or ["fixture"]


def _notes(summaries: list[tuple[Path, Mapping[str, Any]]]) -> str:
    env_vars: list[str] = []
    for _, summary in summaries:
        requirements = _mapping(summary.get("provider_requirements"))
        for value in _string_list(requirements.get("credential_env_vars")):
            _append_unique(env_vars, value)
    if env_vars:
        return "Recorded live-provider smoke requires credential environment variables by name only: " + ", ".join(env_vars) + ". Credential values are not stored."
    return "Fixture-backed LLM smoke result payload; no live provider credentials are required or stored."


def _model_metadata(payload: Mapping[str, Any]) -> dict[str, str]:
    provider = _string(payload.get("provider"))
    model_id = _string(payload.get("model_id"))
    model_family = _string(payload.get("model_family"))
    if not (provider and model_id and model_family):
        raise LLMSmokeResultError("LLM smoke model metadata requires provider, model_id, and model_family")
    return {"provider": provider, "model_id": model_id, "model_family": model_family}


def _combos(summary: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    combos = summary.get("combos")
    return [combo for combo in combos if isinstance(combo, Mapping)] if isinstance(combos, list) else []


def _scenario_rows(combo: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    rows = combo.get("scenario_rows")
    return [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []


def _uncertainty_stated(combo: Mapping[str, Any]) -> bool:
    return any(_string(row.get("llm_confidence")) == "low" for row in _scenario_rows(combo))


def _duration_ms(combo: Mapping[str, Any]) -> int | None:
    durations: list[int] = []
    for row in _scenario_rows(combo):
        duration = row.get("llm_duration_ms")
        if isinstance(duration, int) and duration >= 0:
            durations.append(duration)
        elif isinstance(duration, float) and duration >= 0:
            durations.append(int(round(duration)))
    return sum(durations) if durations else None


def _failure_reason(combo: Mapping[str, Any]) -> str:
    failures = _string_list(combo.get("failures"))
    if failures:
        return "; ".join(failures)
    missing = [hypothesis for hypothesis in _string_list(combo.get("expected_hypotheses")) if hypothesis not in _string_list(combo.get("observed_hypotheses"))]
    if missing:
        return "missing expected hypotheses: " + ", ".join(missing)
    return "LLM smoke result did not pass"


def _failure_class(combo: Mapping[str, Any], *, default: str = "none") -> str:
    value = _string(combo.get("failure_class"))
    return value or default


def _artifact_kind(ref: Mapping[str, Any]) -> str:
    value = _string(ref.get("kind"))
    return value if value in {"artifact_registry", "run_result", "agent_replay", "llm_smoke", "harness_plan", "doc", "other"} else "other"


def _benchmark_set_id(summary: Mapping[str, Any]) -> str:
    value = _string(summary.get("benchmark_set_id"))
    if not value:
        raise LLMSmokeResultError("LLM smoke summary missing benchmark_set_id")
    return value


def _entrant_id(summary: Mapping[str, Any]) -> str:
    entrant = _mapping(summary.get("entrant"))
    value = _string(entrant.get("entrant_id"))
    if not value:
        raise LLMSmokeResultError("LLM smoke summary entrant missing entrant_id")
    return value


def _seed(summaries: list[tuple[Path, Mapping[str, Any]]]) -> int | None:
    for _, summary in summaries:
        seed = summary.get("seed")
        if isinstance(seed, int):
            return seed
    return None


def _generated_collection_mode(summary: Mapping[str, Any]) -> str:
    value = _string(summary.get("generated_incident_collection_mode"))
    return value if value in {"fixture", "real"} else "fixture"


def _archetype(summary: Mapping[str, Any]) -> str:
    value = _string(summary.get("generated_incident_archetype"))
    return value if value in {"fixture", "kind", "linux-vm", "mixed", "unknown"} else "unknown"
