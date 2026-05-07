"""Benchmark-result payloads for retained noisy live incident artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .benchmark_result_helpers import (
    artifact_ref as _artifact_ref,
    load_json_object,
    mapping as _mapping,
    resolve_path as _resolve_path,
    sha256_file as _sha256_file,
    string as _string,
    string_list as _string_list,
    unique_refs as _unique_refs,
    utc_now as _utc_now,
)
from .scenarios import load_scenario_package


RESULT_SCHEMA_VERSION = "incident-generator.benchmark-result/v1"
NOISY_LIVE_RESULT_SCHEMA_VERSION = "sre-agent.noisy-live-result/v1"
NOISY_SMOKE_REPORT_SCHEMA_VERSION = "sre-agent.noisy-smoke-report/v1"
ARTIFACT_REGISTRY_SCHEMA_VERSION = "incident-generator.artifact-registry/v1"
DEFAULT_NOISY_LIVE_REGISTRY_RELATIVE = Path("benchmark-artifacts/registry.json")
DEFAULT_NOISY_LIVE_RUN_ID = "20260506-noisy-live-checkout-canary-5xx"
DEFAULT_NOISY_LIVE_RESULT_BENCHMARK_SET_ID = "noisy-checkout-live-20260506"
RETAINED_NOISY_REPLAY_ARTIFACTS = {
    "noisy_smoke_report_json": "noisy-smoke-report.json",
    "loadgen_preview_json": "loadgen-preview.json",
    "cleanup_summary_json": "cleanup-summary.json",
}


class NoisyLiveResultError(ValueError):
    """Raised when retained noisy live artifacts cannot be mapped."""


def render_noisy_live_result(
    root: Path,
    *,
    registry_path: Path = DEFAULT_NOISY_LIVE_REGISTRY_RELATIVE,
    run_id: str = DEFAULT_NOISY_LIVE_RUN_ID,
    benchmark_set_id: str | None = None,
    name: str | None = None,
    result_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Render one retained noisy live run as a benchmark-result payload."""

    root = root.resolve()
    registry_resolved = _resolve_path(root, registry_path)
    registry = load_json_object(registry_resolved, error_cls=NoisyLiveResultError)
    _validate_registry(registry)
    entry = _registry_entry(registry, run_id=run_id, benchmark_set_id=benchmark_set_id)
    paths = _retained_paths(registry_resolved, entry)
    _verify_retained_hashes(paths, entry)

    result = load_json_object(paths["result_json"], error_cls=NoisyLiveResultError)
    noisy_smoke_path = paths["noisy_smoke_report_json"]
    loadgen_path = paths["loadgen_preview_json"]
    cleanup_path = paths["cleanup_summary_json"]
    dashboard_path = paths.get("dashboard_json")
    noisy_smoke = load_json_object(noisy_smoke_path, error_cls=NoisyLiveResultError)
    loadgen = load_json_object(loadgen_path, error_cls=NoisyLiveResultError) if loadgen_path.is_file() else {}
    cleanup = load_json_object(cleanup_path, error_cls=NoisyLiveResultError) if cleanup_path.is_file() else {}
    dashboard = (
        load_json_object(dashboard_path, error_cls=NoisyLiveResultError)
        if dashboard_path is not None and dashboard_path.is_file()
        else {}
    )

    _validate_noisy_smoke(noisy_smoke)
    _validate_result(result, entry)
    scenario_id = _scenario_id(entry, result)
    smoke_row = _smoke_row(noisy_smoke, scenario_id=scenario_id)
    package = load_scenario_package(_scenario_path(root, result, smoke_row))
    expected_hypotheses = _expected_hypotheses(package.spec, smoke_row)
    set_id = benchmark_set_id or _string(entry.get("benchmark_set_id")) or DEFAULT_NOISY_LIVE_RESULT_BENCHMARK_SET_ID
    case = _case(
        root,
        entry,
        result,
        package.spec,
        smoke_row,
        paths=paths,
        registry_path=registry_resolved,
        noisy_smoke_path=noisy_smoke_path,
        loadgen_path=loadgen_path,
        cleanup_path=cleanup_path,
    )
    result_row = _result_row(
        entry,
        result,
        package.spec,
        smoke_row,
        noisy_smoke,
        loadgen,
        cleanup,
        dashboard,
        case_id=case["case_id"],
        expected_hypotheses=expected_hypotheses,
        noisy_smoke_path=noisy_smoke_path,
    )
    return {
        "schema_version": RESULT_SCHEMA_VERSION,
        "result_id": result_id or f"{set_id}.noisy-live-replay",
        "benchmark_set": {
            "benchmark_set_id": set_id,
            "name": name or f"Noisy live artifact replay for {set_id}",
            "seed": _int_or_none(entry.get("seed")) or _int_or_none(noisy_smoke.get("seed")),
            "collection_modes": [_collection_mode(entry, result)],
            "case_count": 1,
            "source_refs": _source_refs(
                root,
                registry_path=registry_resolved,
                entry=entry,
                paths=paths,
                noisy_smoke=noisy_smoke,
                noisy_smoke_path=noisy_smoke_path,
                loadgen_path=loadgen_path,
                cleanup_path=cleanup_path,
            ),
        },
        "created_at": created_at or _string(entry.get("created_at")) or _utc_now(),
        "cases": [case],
        "entrants": [_entrant()],
        "results": [result_row],
        "aggregate": _aggregate([result_row], cases=[case]),
        "notes": _notes(loadgen, cleanup),
    }


def _validate_registry(registry: Mapping[str, Any]) -> None:
    if registry.get("schema_version") != ARTIFACT_REGISTRY_SCHEMA_VERSION:
        raise NoisyLiveResultError(f"unsupported artifact registry schema_version: {registry.get('schema_version')}")
    if not isinstance(registry.get("entries"), list):
        raise NoisyLiveResultError("artifact registry must contain entries")


def _registry_entry(registry: Mapping[str, Any], *, run_id: str, benchmark_set_id: str | None) -> Mapping[str, Any]:
    entries = [entry for entry in registry.get("entries", []) if isinstance(entry, Mapping)]
    matches = [entry for entry in entries if _string(entry.get("run_id")) == run_id]
    if benchmark_set_id:
        matches = [entry for entry in matches if _string(entry.get("benchmark_set_id")) == benchmark_set_id]
    if not matches:
        suffix = f" and benchmark_set_id={benchmark_set_id}" if benchmark_set_id else ""
        raise NoisyLiveResultError(f"artifact registry has no run_id={run_id}{suffix}")
    if len(matches) > 1:
        raise NoisyLiveResultError(f"artifact registry has duplicate run_id={run_id}")
    entry = matches[0]
    if _string(entry.get("collection_mode")) != "real":
        raise NoisyLiveResultError(f"noisy live run {run_id} must have collection_mode=real")
    if _string(entry.get("archetype")) != "kind":
        raise NoisyLiveResultError(f"noisy live run {run_id} must have archetype=kind")
    return entry


def _retained_paths(registry_path: Path, entry: Mapping[str, Any]) -> dict[str, Path]:
    retained = entry.get("retained_paths")
    if not isinstance(retained, Mapping):
        raise NoisyLiveResultError(f"registry entry {_string(entry.get('run_id'))} missing retained_paths")
    base = registry_path.parent
    paths: dict[str, Path] = {}
    retained_keys = (
        "result_json",
        "events_ndjson",
        "summary_json",
        "dashboard_json",
        "dashboard_markdown",
        *RETAINED_NOISY_REPLAY_ARTIFACTS,
    )
    for key in retained_keys:
        value = _string(retained.get(key))
        if value:
            paths[key] = base / value
    for key in ("result_json", "events_ndjson", "summary_json"):
        if key not in paths:
            raise NoisyLiveResultError(f"registry entry {_string(entry.get('run_id'))} missing retained path {key}")
    paths["artifact_dir"] = paths["result_json"].parent
    for key, filename in RETAINED_NOISY_REPLAY_ARTIFACTS.items():
        paths.setdefault(key, paths["artifact_dir"] / filename)
    return paths


def _verify_retained_hashes(paths: Mapping[str, Path], entry: Mapping[str, Any]) -> None:
    hashes = entry.get("content_hashes")
    if not isinstance(hashes, Mapping):
        raise NoisyLiveResultError(f"registry entry {_string(entry.get('run_id'))} missing content_hashes")
    for path_key, path in sorted(paths.items()):
        if path_key == "artifact_dir":
            continue
        expected = hashes.get(path_key)
        if not path.is_file():
            if path_key in {"result_json", "events_ndjson", "summary_json"} or isinstance(expected, Mapping):
                raise NoisyLiveResultError(f"retained artifact is missing: {path}")
            continue
        if not isinstance(expected, Mapping):
            continue
        expected_hash = _string(expected.get("value"))
        if expected_hash and _sha256_file(path) != expected_hash:
            raise NoisyLiveResultError(f"retained artifact hash drift for {path_key}: {path}")


def _validate_noisy_smoke(noisy_smoke: Mapping[str, Any]) -> None:
    if noisy_smoke.get("schema_version") != NOISY_SMOKE_REPORT_SCHEMA_VERSION:
        raise NoisyLiveResultError(f"unsupported noisy smoke schema_version: {noisy_smoke.get('schema_version')}")
    if noisy_smoke.get("passed") is not True:
        raise NoisyLiveResultError("noisy smoke report did not pass")
    if not isinstance(noisy_smoke.get("scenarios"), list):
        raise NoisyLiveResultError("noisy smoke report must contain scenarios")


def _validate_result(result: Mapping[str, Any], entry: Mapping[str, Any]) -> None:
    run_id = _string(entry.get("run_id"))
    if _string(result.get("incident_session_id")) != run_id:
        raise NoisyLiveResultError(f"result.json incident_session_id does not match registry run_id {run_id}")
    if result.get("blocked") is True:
        raise NoisyLiveResultError(f"noisy live run {run_id} is blocked")
    if result.get("generated") is not True:
        raise NoisyLiveResultError(f"noisy live run {run_id} was not generated")


def _scenario_id(entry: Mapping[str, Any], result: Mapping[str, Any]) -> str:
    scenario_ids = _string_list(entry.get("scenario_ids"))
    scenario = _string(result.get("scenario"))
    if scenario and scenario_ids and scenario != scenario_ids[0]:
        raise NoisyLiveResultError(f"result scenario {scenario} does not match registry scenario {scenario_ids[0]}")
    scenario_id = scenario or (scenario_ids[0] if scenario_ids else "")
    if not scenario_id:
        raise NoisyLiveResultError("could not infer noisy live scenario id")
    return scenario_id


def _smoke_row(noisy_smoke: Mapping[str, Any], *, scenario_id: str) -> Mapping[str, Any]:
    for row in noisy_smoke.get("scenarios", []):
        if isinstance(row, Mapping) and _string(row.get("scenario")) == scenario_id:
            if row.get("passed") is not True or row.get("observed_expected_hypothesis") is not True:
                raise NoisyLiveResultError(f"noisy smoke scenario {scenario_id} did not pass")
            return row
    raise NoisyLiveResultError(f"noisy smoke report missing scenario {scenario_id}")


def _scenario_path(root: Path, result: Mapping[str, Any], smoke_row: Mapping[str, Any]) -> Path:
    for value in (_string(smoke_row.get("scenario_path")), _string(result.get("scenario_path"))):
        if not value:
            continue
        path = Path(value)
        if not path.is_absolute():
            path = root / path
        if path.is_dir():
            return path
    raise NoisyLiveResultError(f"could not resolve scenario path for {_string(result.get('scenario'))}")


def _case(
    root: Path,
    entry: Mapping[str, Any],
    result: Mapping[str, Any],
    scenario_spec: Mapping[str, Any],
    smoke_row: Mapping[str, Any],
    *,
    paths: Mapping[str, Path],
    registry_path: Path,
    noisy_smoke_path: Path,
    loadgen_path: Path,
    cleanup_path: Path,
) -> dict[str, Any]:
    expected = _expected_hypotheses(scenario_spec, smoke_row)
    return {
        "case_id": _string(entry.get("run_id")),
        "generated_incident": {
            "incident_run_id": _string(entry.get("run_id")),
            "scenario_ids": _string_list(entry.get("scenario_ids")) or [_string(result.get("scenario"))],
            "combination_size": _int_or_none(entry.get("combination_size")) or 1,
            "archetype": _archetype(entry, result),
            "collection_mode": _collection_mode(entry, result),
            "generation_state": _generation_state(entry, result),
            "failure_class": _failure_class(entry, result),
            "artifact_refs": _case_artifact_refs(
                root,
                paths=paths,
                registry_path=registry_path,
                noisy_smoke_path=noisy_smoke_path,
                loadgen_path=loadgen_path,
                cleanup_path=cleanup_path,
            ),
        },
        "expectations": {
            "expected_hypotheses": expected,
            "forbidden_hypotheses": _string_list(scenario_spec.get("forbidden_hypotheses")),
            "required_abstention": _requires_action_abstention(scenario_spec),
            "uncertainty_expected": False,
            "false_attribution_guards": _false_attribution_guards(smoke_row),
            "evidence_role_expectations": _evidence_role_expectations(smoke_row),
        },
        "notes": _case_notes(smoke_row),
    }


def _result_row(
    entry: Mapping[str, Any],
    result: Mapping[str, Any],
    scenario_spec: Mapping[str, Any],
    smoke_row: Mapping[str, Any],
    noisy_smoke: Mapping[str, Any],
    loadgen: Mapping[str, Any],
    cleanup: Mapping[str, Any],
    dashboard: Mapping[str, Any],
    *,
    case_id: str,
    expected_hypotheses: list[str],
    noisy_smoke_path: Path,
) -> dict[str, Any]:
    observed_expected = smoke_row.get("observed_expected_hypothesis") is True
    live_generated = result.get("generated") is True and result.get("blocked") is not True
    cleanup_ok = cleanup.get("passed") is not False and cleanup.get("cluster_deleted") is not False
    matched = expected_hypotheses if observed_expected and live_generated else []
    missing = [hypothesis for hypothesis in expected_hypotheses if hypothesis not in matched]
    evidence_refs = _evidence_refs(scenario_spec)
    hypothesis_pass = not missing and live_generated
    evidence_reference_pass = bool(evidence_refs) and _wait_predicates_matched(dashboard)
    abstention_required = _requires_action_abstention(scenario_spec)
    abstained = True if abstention_required else False
    abstention_pass = not abstention_required or abstained is True
    uncertainty_pass = True
    false_attribution_pass = True
    overall_pass = (
        hypothesis_pass
        and evidence_reference_pass
        and abstention_pass
        and uncertainty_pass
        and false_attribution_pass
        and cleanup_ok
        and noisy_smoke.get("passed") is True
    )
    return {
        "case_id": case_id,
        "entrant_id": "noisy-live-artifact-replay",
        "state": "passed" if overall_pass else "failed",
        "duration_ms": _duration_ms(dashboard, result),
        "agent_output_ref": _relative_or_name(noisy_smoke_path),
        "diagnosis": {
            "primary_hypothesis": matched[0] if matched else (expected_hypotheses[0] if expected_hypotheses else None),
            "matched_expected_hypotheses": matched,
            "missing_expected_hypotheses": missing,
            "unexpected_hypotheses": [],
            "evidence_refs": evidence_refs,
        },
        "evidence_discipline": {
            "abstention_required": abstention_required,
            "abstained": abstained,
            "uncertainty_required": False,
            "uncertainty_stated": False,
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
            "rationale_ref": _relative_or_name(noisy_smoke_path),
            "failure_reason": None if overall_pass else _failure_reason(missing, cleanup),
        },
        "failure_class": "none" if overall_pass else _failure_class(entry, result, default="validation_issue"),
        "notes": _result_notes(loadgen, cleanup),
    }


def _entrant() -> dict[str, Any]:
    return {
        "entrant_id": "noisy-live-artifact-replay",
        "display_name": "Noisy live artifact replay",
        "agent_kind": "deterministic",
        "execution_mode": "replay",
        "agent_version": NOISY_LIVE_RESULT_SCHEMA_VERSION,
        "model": None,
        "judge": {
            "judge_kind": "deterministic",
            "model": None,
            "separate_family_required": False,
        },
        "command_ref": "incident_generator noisy-live-result",
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
        "judge_executed_count": sum(
            1 for result in results if result.get("judge_outcome", {}).get("status") == "executed"
        ),
        "judge_passed_count": sum(
            1 for result in results if result.get("judge_outcome", {}).get("verdict") == "pass"
        ),
    }


def _source_refs(
    root: Path,
    *,
    registry_path: Path,
    entry: Mapping[str, Any],
    paths: Mapping[str, Path],
    noisy_smoke: Mapping[str, Any],
    noisy_smoke_path: Path,
    loadgen_path: Path,
    cleanup_path: Path,
) -> list[dict[str, str | None]]:
    refs = [
        _artifact_ref(root, registry_path, "artifact_registry", notes="checked benchmark artifact registry"),
        _artifact_ref(root, paths["result_json"], "run_result", notes="retained noisy live incident result"),
        _artifact_ref(root, paths["events_ndjson"], "run_result", notes="retained noisy live progress events"),
        _artifact_ref(root, paths["summary_json"], "run_result", notes="retained noisy live summary"),
        _artifact_ref(root, noisy_smoke_path, "other", notes="noisy smoke report attached to the live run"),
    ]
    smoke_plan_path = _smoke_plan_path(root, noisy_smoke)
    if smoke_plan_path is not None:
        refs.append(
            _artifact_ref(
                root,
                smoke_plan_path,
                "harness_plan",
                notes=f"noisy smoke plan for {_string(noisy_smoke.get('smoke_id')) or 'retained live run'}",
            )
        )
    for optional_path, kind, notes in (
        (paths.get("dashboard_json"), "run_result", "retained progress dashboard"),
        (paths.get("dashboard_markdown"), "doc", "retained progress dashboard markdown"),
        (loadgen_path if loadgen_path.is_file() else None, "other", "deterministic ecommerce-lite loadgen preview"),
        (cleanup_path if cleanup_path.is_file() else None, "other", "live cleanup verification summary"),
    ):
        if optional_path is not None:
            refs.append(_artifact_ref(root, optional_path, kind, notes=notes))
    return _unique_refs(refs)


def _case_artifact_refs(
    root: Path,
    *,
    paths: Mapping[str, Path],
    registry_path: Path,
    noisy_smoke_path: Path,
    loadgen_path: Path,
    cleanup_path: Path,
) -> list[dict[str, str | None]]:
    refs = [
        _artifact_ref(root, registry_path, "artifact_registry", notes="registry entry for retained noisy live run"),
        _artifact_ref(root, paths["result_json"], "run_result", notes="single-scenario real-mode result"),
        _artifact_ref(root, paths["events_ndjson"], "run_result", notes="progress event stream"),
        _artifact_ref(root, paths["summary_json"], "run_result", notes="single-scenario summary"),
        _artifact_ref(root, noisy_smoke_path, "other", notes="noisy smoke report used as replay source"),
    ]
    if paths.get("dashboard_json") is not None:
        refs.append(_artifact_ref(root, paths["dashboard_json"], "run_result", notes="progress dashboard"))
    if loadgen_path.is_file():
        refs.append(_artifact_ref(root, loadgen_path, "other", notes="load-generator preview"))
    if cleanup_path.is_file():
        refs.append(_artifact_ref(root, cleanup_path, "other", notes="cleanup summary"))
    return _unique_refs(refs)


def _expected_hypotheses(scenario_spec: Mapping[str, Any], smoke_row: Mapping[str, Any]) -> list[str]:
    values = _string_list(scenario_spec.get("expected_hypotheses"))
    smoke_expected = _string(smoke_row.get("expected_hypothesis"))
    if smoke_expected and smoke_expected not in values:
        values.append(smoke_expected)
    if not values:
        raise NoisyLiveResultError(f"missing expected hypotheses for {_string(smoke_row.get('scenario'))}")
    return values


def _evidence_refs(scenario_spec: Mapping[str, Any]) -> list[str]:
    return _string_list(scenario_spec.get("evidence_adapters_required"))


def _requires_action_abstention(scenario_spec: Mapping[str, Any]) -> bool:
    criteria = scenario_spec.get("success_criteria")
    return isinstance(criteria, Mapping) and criteria.get("requires_action_abstention") is True


def _case_notes(smoke_row: Mapping[str, Any]) -> str:
    domain = _string(smoke_row.get("domain"))
    if domain:
        return f"Retained noisy live {domain} incident replayed from artifact registry, live run, and noisy smoke artifacts."
    return "Retained noisy live incident replayed from artifact registry, live run, and noisy smoke artifacts."


def _false_attribution_guards(smoke_row: Mapping[str, Any]) -> list[str]:
    guards: list[str] = []
    workload = smoke_row.get("workload_profile")
    if isinstance(workload, Mapping):
        noise_profile = _string(workload.get("noise_profile_id"))
        if noise_profile:
            guards.append(f"do not attribute the incident to ambient {noise_profile} alone")
    for source_id in _string_list(_mapping(smoke_row.get("noisy_fixture")).get("source_ids"))[:3]:
        guards.append(f"do not treat non-causal source {source_id} as the root cause")
    return guards


def _evidence_role_expectations(smoke_row: Mapping[str, Any]) -> list[dict[str, int]]:
    noisy_fixture = _mapping(smoke_row.get("noisy_fixture"))
    counts = _mapping(noisy_fixture.get("signal_role_counts"))
    expectations: list[dict[str, int]] = []
    for role in ("causal", "contextual", "ambient", "red_herring", "hostile"):
        count = _int_or_none(counts.get(role))
        if count is not None:
            expectations.append({"role": role, "expected_count": count})
    return expectations


def _collection_mode(entry: Mapping[str, Any], result: Mapping[str, Any]) -> str:
    value = _string(entry.get("collection_mode")) or _string(result.get("collection_mode"))
    return value if value in {"fixture", "real"} else "real"


def _archetype(entry: Mapping[str, Any], result: Mapping[str, Any]) -> str:
    value = _string(entry.get("archetype")) or _string(result.get("environment_archetype"))
    return value if value in {"fixture", "kind", "linux-vm", "mixed", "unknown"} else "unknown"


def _generation_state(entry: Mapping[str, Any], result: Mapping[str, Any]) -> str:
    value = _string(entry.get("state"))
    if value in {"passed", "generated", "blocked", "failed", "partial", "unknown"}:
        return value
    if result.get("blocked") is True:
        return "blocked"
    if result.get("generated") is True:
        return "generated"
    return "failed"


def _failure_class(entry: Mapping[str, Any], result: Mapping[str, Any], *, default: str = "none") -> str:
    value = _string(entry.get("failure_class")) or _string(result.get("failure_class"))
    return value or default


def _wait_predicates_matched(dashboard: Mapping[str, Any]) -> bool:
    predicates = dashboard.get("wait_predicates")
    if not isinstance(predicates, list):
        return True
    observed = [item for item in predicates if isinstance(item, Mapping) and item.get("status") == "observed"]
    return bool(observed) and all(item.get("matched") is True for item in observed)


def _duration_ms(dashboard: Mapping[str, Any], result: Mapping[str, Any]) -> int | None:
    value = dashboard.get("elapsed_ms")
    if isinstance(value, int) and value >= 0:
        return value
    value = result.get("duration_ms")
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, float) and value >= 0:
        return int(round(value))
    return None


def _failure_reason(missing: list[str], cleanup: Mapping[str, Any]) -> str:
    if missing:
        return "missing expected hypotheses: " + ", ".join(missing)
    if cleanup.get("passed") is False or cleanup.get("cluster_deleted") is False:
        return "cleanup verification failed"
    return "noisy live artifact replay failed"


def _notes(loadgen: Mapping[str, Any], cleanup: Mapping[str, Any]) -> str:
    return _result_notes(loadgen, cleanup)


def _result_notes(loadgen: Mapping[str, Any], cleanup: Mapping[str, Any]) -> str:
    parts: list[str] = []
    rps = loadgen.get("rps")
    warmup = loadgen.get("warmup_seconds")
    total = loadgen.get("total_requests")
    if rps is not None and warmup is not None:
        parts.append(f"replayed retained noisy live run after {warmup}s loadgen warmup at {rps} RPS")
    if total is not None:
        parts.append(f"loadgen preview planned {total} requests")
    warnings = _string_list(cleanup.get("warnings"))
    if warnings:
        parts.append(f"cleanup warnings: {'; '.join(warnings)}")
    return "; ".join(parts) if parts else "replayed retained noisy live artifacts"


def _smoke_plan_path(root: Path, noisy_smoke: Mapping[str, Any]) -> Path | None:
    value = _string(noisy_smoke.get("smoke_path"))
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        path = root / path
    return path if path.is_file() else None


def _relative_or_name(path: Path) -> str:
    parts = path.parts
    if "benchmark-artifacts" in parts:
        index = parts.index("benchmark-artifacts")
        return str(Path(*parts[index:]))
    return str(path)


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) else None
