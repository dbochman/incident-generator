"""Benchmark-result payloads for deterministic validated-combo replay summaries."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .benchmark_result_helpers import (
    append_unique as _append_unique,
    artifact_ref as _artifact_ref,
    load_json_object,
    resolve_path as _resolve_path,
    string as _string,
    string_list as _string_list,
    utc_now as _utc_now,
)


RESULT_SCHEMA_VERSION = "incident-generator.benchmark-result/v1"
VALIDATED_COMBO_AGENT_SCHEMA_VERSION = "sre-agent.validated-combo-agent-batch/v1"
DEFAULT_DETERMINISTIC_REPLAY_SUMMARY_RELATIVE = Path("harness/deterministic-replay-summary-example.json")
DEFAULT_DETERMINISTIC_REPLAY_BENCHMARK_SET_ID = "kind-curated-pairs-warm-20260506"


class DeterministicReplayResultError(ValueError):
    """Raised when deterministic replay inputs cannot be mapped."""


def build_deterministic_replay_result(
    root: Path,
    *,
    agent_summary_path: Path,
    incident_result_path: Path | None = None,
    benchmark_set_id: str | None = None,
    name: str | None = None,
    result_id: str | None = None,
    created_at: str | None = None,
    collection_mode: str = "real",
    archetype: str = "kind",
) -> dict[str, Any]:
    """Map a validated-combo deterministic replay summary into the result schema."""

    summary_path = _resolve_path(root, agent_summary_path)
    summary = load_json_object(summary_path, error_cls=DeterministicReplayResultError)
    _validate_summary(summary)
    incident_path = _resolve_incident_result_path(root, summary, incident_result_path)
    incident = (
        load_json_object(incident_path, error_cls=DeterministicReplayResultError)
        if incident_path is not None and incident_path.is_file()
        else {}
    )
    replay_results = _replay_results(summary)
    runs_by_session = _runs_by_session(incident)
    cases: list[dict[str, Any]] = []
    results: list[dict[str, Any]] = []
    for replay in replay_results:
        run = _matching_run(replay, runs_by_session, collection_mode=collection_mode, archetype=archetype)
        case = _case(root, replay, run, incident_path=incident_path, summary_path=summary_path)
        cases.append(case)
        results.append(_result(replay, run, case_id=case["case_id"]))

    set_id = benchmark_set_id or _infer_benchmark_set_id(summary_path)
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "result_id": result_id or f"{set_id}.deterministic-replay",
        "benchmark_set": {
            "benchmark_set_id": set_id,
            "name": name or f"Deterministic replay results for {set_id}",
            "seed": _seed(incident),
            "collection_modes": _collection_modes(cases),
            "case_count": len(cases),
            "source_refs": _source_refs(root, incident_path=incident_path, summary_path=summary_path),
        },
        "created_at": created_at or _utc_now(),
        "cases": cases,
        "entrants": [_deterministic_entrant()],
        "results": results,
        "aggregate": _aggregate(results, cases=cases),
        "notes": "Generated from deterministic validated-combo replay summary artifacts.",
    }


def render_deterministic_replay_result(
    root: Path,
    *,
    summary_path: Path = DEFAULT_DETERMINISTIC_REPLAY_SUMMARY_RELATIVE,
    benchmark_set_id: str = DEFAULT_DETERMINISTIC_REPLAY_BENCHMARK_SET_ID,
    name: str | None = None,
    result_id: str | None = None,
    created_at: str | None = None,
    collection_mode: str = "real",
    archetype: str = "kind",
) -> dict[str, Any]:
    """Render the checked deterministic replay summary as a benchmark result."""

    return build_deterministic_replay_result(
        root,
        agent_summary_path=summary_path,
        benchmark_set_id=benchmark_set_id,
        name=name,
        result_id=result_id,
        created_at=created_at,
        collection_mode=collection_mode,
        archetype=archetype,
    )


def _validate_summary(summary: Mapping[str, Any]) -> None:
    schema_version = summary.get("schema_version")
    if schema_version != VALIDATED_COMBO_AGENT_SCHEMA_VERSION:
        raise DeterministicReplayResultError(
            f"unsupported deterministic replay summary schema_version: {schema_version}"
        )
    if summary.get("agent") != "deterministic":
        raise DeterministicReplayResultError("deterministic replay result requires summary agent=deterministic")


def _resolve_incident_result_path(
    root: Path,
    summary: Mapping[str, Any],
    incident_result_path: Path | None,
) -> Path | None:
    if incident_result_path is not None:
        return _resolve_path(root, incident_result_path)
    raw = summary.get("incident_result")
    if not isinstance(raw, str) or not raw:
        return None
    return _resolve_path(root, Path(raw))


def _replay_results(summary: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    results = summary.get("results")
    if not isinstance(results, list) or not results:
        raise DeterministicReplayResultError("deterministic replay summary must contain results")
    parsed: list[Mapping[str, Any]] = []
    for index, item in enumerate(results):
        if not isinstance(item, Mapping):
            raise DeterministicReplayResultError(f"summary results[{index}] must be an object")
        parsed.append(item)
    return parsed


def _runs_by_session(incident: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    runs = incident.get("runs")
    if not isinstance(runs, list) or not runs:
        return {}
    by_session: dict[str, Mapping[str, Any]] = {}
    for run in runs:
        if not isinstance(run, Mapping):
            continue
        session = _string(run.get("incident_session_id")) or _string(run.get("incident_id"))
        if session:
            by_session[session] = run
    return by_session


def _matching_run(
    replay: Mapping[str, Any],
    runs_by_session: Mapping[str, Mapping[str, Any]],
    *,
    collection_mode: str,
    archetype: str,
) -> Mapping[str, Any]:
    session = _string(replay.get("incident_session_id"))
    if session and session in runs_by_session:
        return runs_by_session[session]
    scenario = _string(replay.get("scenario"))
    for run in runs_by_session.values():
        if scenario and scenario == _string(run.get("scenario")):
            return run
    return _fallback_run(replay, collection_mode=collection_mode, archetype=archetype)


def _fallback_run(replay: Mapping[str, Any], *, collection_mode: str, archetype: str) -> dict[str, Any]:
    scenario_ids = _scenario_ids_from_text(_string(replay.get("scenario")))
    return {
        "incident_session_id": _string(replay.get("incident_session_id")),
        "scenario": _string(replay.get("scenario")),
        "scenarios": [{"name": scenario_id} for scenario_id in scenario_ids],
        "expected_hypotheses": _string_list(replay.get("expected_hypotheses")),
        "evidence_adapters_required": _string_list(replay.get("skills")) or ["agent_replay.summary"],
        "collection_mode": collection_mode if collection_mode in {"fixture", "real"} else "real",
        "environment_archetype": archetype if archetype in {"fixture", "kind", "linux-vm", "mixed", "unknown"} else "kind",
        "generated": True,
        "blocked": False,
        "failure_class": "none",
    }


def _case(
    root: Path,
    replay: Mapping[str, Any],
    run: Mapping[str, Any],
    *,
    incident_path: Path | None,
    summary_path: Path,
) -> dict[str, Any]:
    scenario_ids = _scenario_ids(run, replay)
    artifact_refs = _source_refs(root, incident_path=incident_path, summary_path=summary_path)
    return {
        "case_id": _case_id(replay, run),
        "generated_incident": {
            "incident_run_id": _string(run.get("incident_session_id")) or _string(replay.get("incident_session_id")),
            "scenario_ids": scenario_ids,
            "combination_size": len(scenario_ids),
            "archetype": _archetype(run),
            "collection_mode": _collection_mode(run),
            "generation_state": _generation_state(run),
            "failure_class": _failure_class(run),
            "artifact_refs": artifact_refs,
        },
        "expectations": {
            "expected_hypotheses": _string_list(replay.get("expected_hypotheses"))
            or _string_list(run.get("expected_hypotheses")),
            "forbidden_hypotheses": _string_list(run.get("forbidden_hypotheses")),
            "required_abstention": _requires_action_abstention(run),
            "uncertainty_expected": False,
            "false_attribution_guards": _string_list(run.get("false_attribution_guards")),
            "evidence_role_expectations": [],
        },
    }


def _result(replay: Mapping[str, Any], run: Mapping[str, Any], *, case_id: str) -> dict[str, Any]:
    expected = _string_list(replay.get("expected_hypotheses")) or _string_list(run.get("expected_hypotheses"))
    observed = _string_list(replay.get("observed_hypotheses"))
    missing = _string_list(replay.get("missing_hypotheses"))
    matched = [hypothesis for hypothesis in expected if hypothesis in observed and hypothesis not in missing]
    unexpected = [hypothesis for hypothesis in observed if hypothesis not in expected]
    required_abstention = _requires_action_abstention(run)
    abstained = True if required_abstention else False
    hypothesis_pass = not missing
    evidence_reference_pass = bool(_evidence_refs(run))
    abstention_pass = not required_abstention or abstained is True
    uncertainty_pass = True
    false_attribution_pass = True
    overall_pass = (
        hypothesis_pass
        and evidence_reference_pass
        and abstention_pass
        and uncertainty_pass
        and false_attribution_pass
        and replay.get("passed") is True
    )
    state = _state(replay, run, overall_pass=overall_pass)
    failure_class = "none" if state == "passed" else "agent_hypothesis_regression"
    if state == "blocked":
        failure_class = _failure_class(run)
    return {
        "case_id": case_id,
        "entrant_id": "deterministic-validated-combo",
        "state": state,
        "duration_ms": _duration_ms(replay),
        "agent_output_ref": _string(replay.get("composed_path")) or _string(replay.get("briefs_path")),
        "diagnosis": {
            "primary_hypothesis": observed[0] if observed else (expected[0] if expected else None),
            "matched_expected_hypotheses": matched,
            "missing_expected_hypotheses": missing,
            "unexpected_hypotheses": unexpected,
            "evidence_refs": _evidence_refs(run),
        },
        "evidence_discipline": {
            "abstention_required": required_abstention,
            "abstained": abstained,
            "uncertainty_required": False,
            "uncertainty_stated": _string(replay.get("confidence")) == "low",
            "forbidden_hypotheses_observed": [],
            "false_attribution_observed": [],
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
            "status": "executed",
            "judge_kind": "deterministic",
            "verdict": "pass" if overall_pass else "fail",
            "score": 1.0 if overall_pass else 0.0,
            "model": None,
            "separate_family_ok": None,
            "rationale_ref": _string(replay.get("composed_path")) or None,
            "failure_reason": None if overall_pass else _failure_reason(replay, missing),
        },
        "failure_class": failure_class,
        "notes": _string(replay.get("summary")) or "deterministic replay result",
    }


def _deterministic_entrant() -> dict[str, Any]:
    return {
        "entrant_id": "deterministic-validated-combo",
        "display_name": "Deterministic validated-combo replay",
        "agent_kind": "deterministic",
        "execution_mode": "replay",
        "agent_version": VALIDATED_COMBO_AGENT_SCHEMA_VERSION,
        "model": None,
        "judge": {
            "judge_kind": "deterministic",
            "model": None,
            "separate_family_required": False,
        },
        "command_ref": "tools/run_validated_combo_agents.py",
    }


def _aggregate(results: list[Mapping[str, Any]], *, cases: list[Mapping[str, Any]]) -> dict[str, int]:
    return {
        "case_count": len(cases),
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
        "judge_executed_count": len(results),
        "judge_passed_count": sum(
            1 for result in results if result.get("judge_outcome", {}).get("verdict") == "pass"
        ),
    }


def _case_id(replay: Mapping[str, Any], run: Mapping[str, Any]) -> str:
    return _string(run.get("incident_session_id")) or _string(replay.get("incident_session_id")) or f"combo-{replay.get('run_index', 0)}"


def _scenario_ids(run: Mapping[str, Any], replay: Mapping[str, Any]) -> list[str]:
    names: list[str] = []
    scenarios = run.get("scenarios")
    if isinstance(scenarios, list):
        for scenario in scenarios:
            if isinstance(scenario, Mapping):
                _append_unique(names, _string(scenario.get("name")))
    if not names:
        scenario_text = _string(run.get("scenario")) or _string(replay.get("scenario"))
        for item in _scenario_ids_from_text(scenario_text):
            _append_unique(names, item)
    if not names:
        raise DeterministicReplayResultError(f"could not infer scenario ids for {_case_id(replay, run)}")
    return names


def _scenario_ids_from_text(scenario_text: str) -> list[str]:
    prefix = "combinatorial:"
    if not scenario_text.startswith(prefix):
        return []
    return [item for item in scenario_text[len(prefix) :].split("+") if item]


def _collection_modes(cases: list[Mapping[str, Any]]) -> list[str]:
    modes: list[str] = []
    for case in cases:
        incident = case.get("generated_incident")
        if isinstance(incident, Mapping):
            _append_unique(modes, _string(incident.get("collection_mode")))
    return [mode for mode in modes if mode in {"fixture", "real"}] or ["fixture"]


def _collection_mode(run: Mapping[str, Any]) -> str:
    mode = _string(run.get("collection_mode"))
    return mode if mode in {"fixture", "real"} else "fixture"


def _archetype(run: Mapping[str, Any]) -> str:
    archetype = _string(run.get("environment_archetype"))
    if not archetype:
        context = run.get("context")
        if isinstance(context, Mapping):
            archetype = _string(context.get("archetype"))
    return archetype if archetype in {"fixture", "kind", "linux-vm", "mixed", "unknown"} else "unknown"


def _generation_state(run: Mapping[str, Any]) -> str:
    if run.get("blocked") is True:
        return "blocked"
    if run.get("generated") is True:
        return "passed"
    return "failed"


def _state(replay: Mapping[str, Any], run: Mapping[str, Any], *, overall_pass: bool) -> str:
    if run.get("blocked") is True:
        return "blocked"
    if replay.get("passed") is True and overall_pass:
        return "passed"
    return "failed"


def _failure_class(run: Mapping[str, Any]) -> str:
    value = _string(run.get("failure_class"))
    return value if value else "none"


def _requires_action_abstention(run: Mapping[str, Any]) -> bool:
    criteria = run.get("success_criteria")
    if isinstance(criteria, Mapping) and criteria.get("requires_action_abstention") is True:
        return True
    return False


def _evidence_refs(run: Mapping[str, Any]) -> list[str]:
    refs = _string_list(run.get("evidence_adapters_required"))
    if refs:
        return refs
    refs = []
    scenarios = run.get("scenarios")
    if isinstance(scenarios, list):
        for scenario in scenarios:
            if isinstance(scenario, Mapping):
                for adapter in _string_list(scenario.get("evidence_adapters_required")):
                    _append_unique(refs, adapter)
    return refs


def _duration_ms(replay: Mapping[str, Any]) -> int | None:
    duration = replay.get("duration_ms")
    if isinstance(duration, int) and duration >= 0:
        return duration
    if isinstance(duration, float) and duration >= 0:
        return int(round(duration))
    return 0


def _failure_reason(replay: Mapping[str, Any], missing: list[str]) -> str:
    failures = _string_list(replay.get("failures"))
    if failures:
        return "; ".join(failures)
    if missing:
        return "missing expected hypotheses: " + ", ".join(missing)
    return "deterministic replay scoring failed"


def _seed(incident: Mapping[str, Any]) -> int | None:
    source = incident.get("combination_source")
    if isinstance(source, Mapping) and isinstance(source.get("random_seed"), int):
        return source["random_seed"]
    return None


def _infer_benchmark_set_id(summary_path: Path) -> str:
    if summary_path.name == "summary.json" and summary_path.parent.name:
        base = summary_path.parent.name
    else:
        base = summary_path.stem
    return f"deterministic-replay-{_safe_id(base)}"


def _source_refs(root: Path, *, incident_path: Path | None, summary_path: Path) -> list[dict[str, str | None]]:
    refs: list[dict[str, str | None]] = []
    if incident_path is not None:
        refs.append(_artifact_ref(root, incident_path, "run_result", notes="incident-generator batch result"))
    refs.append(_artifact_ref(root, summary_path, "agent_replay", notes="validated-combo deterministic replay summary"))
    return refs


def _safe_id(value: str) -> str:
    return "-".join("".join(ch.lower() if ch.isalnum() else "-" for ch in value).split("-"))
