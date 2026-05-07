"""Temporal and cascading benchmark model reports."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Mapping

from .benchmark_result_helpers import (
    relative_path as _relative_path,
    resolve_path as _resolve_path,
    stable_hash as _stable_hash,
)
from .parsers import load_yaml
from .scenarios import list_scenario_packages, load_scenario_package


REPORT_SCHEMA_VERSION = "sre-agent.temporal-benchmark-model-report/v1"
MODEL_SCHEMA_VERSION = "sre-agent.temporal-incident-benchmark/v1"
DEFAULT_TEMPORAL_MODEL_RELATIVE = Path("harness/cascading-temporal-incident-model.yaml")


def render_temporal_benchmark_model(root: Path, *, model_path: Path | None = None) -> dict[str, Any]:
    """Render a semantic report for a temporal incident benchmark model."""
    root = root.resolve()
    model_path = _resolve_path(root, model_path or DEFAULT_TEMPORAL_MODEL_RELATIVE)
    model = load_yaml(model_path)
    scenario_catalog = {package.name: package for package in _load_catalog(root)}
    scenario_ids = _string_list(model.get("scenario_ids", []))
    selected_packages = [scenario_catalog[scenario_id] for scenario_id in scenario_ids if scenario_id in scenario_catalog]
    phases = [phase for phase in model.get("timeline", {}).get("phases", []) if isinstance(phase, dict)]
    causal_links = [link for link in model.get("causal_links", []) if isinstance(link, dict)]
    scenario_hypotheses = _scenario_hypotheses(selected_packages)
    failures = []
    failures.extend(_top_level_failures(model, scenario_catalog, scenario_ids))
    failures.extend(_phase_failures(phases, scenario_ids, scenario_hypotheses))
    failures.extend(_causal_link_failures(phases, causal_links))
    phase_rows = [_phase_row(phase) for phase in sorted(phases, key=lambda item: int(item.get("order") or 0))]
    payload: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "model_schema_version": str(model.get("schema_version") or ""),
        "model_id": str(model.get("benchmark_id") or model_path.stem),
        "model_path": _relative_path(root, model_path),
        "description": str(model.get("description") or ""),
        "collection_mode": str(model.get("collection_mode") or ""),
        "scenario_ids": scenario_ids,
        "scenario_paths": [_relative_path(root, package.path) for package in selected_packages],
        "phase_count": len(phase_rows),
        "causal_link_count": len(causal_links),
        "delayed_symptom_count": sum(len(row["delayed_symptoms"]) for row in phase_rows),
        "expected_hypotheses": sorted({hypothesis for row in phase_rows for hypothesis in row["expected_hypotheses"]["active"]}),
        "coverage": _coverage(selected_packages, phase_rows, causal_links),
        "phases": phase_rows,
        "causal_links": copy.deepcopy(causal_links),
        "scoring": copy.deepcopy(model.get("scoring", {})),
        "passed": not failures,
        "failures": failures,
    }
    payload["artifact_hash"] = _stable_hash(payload)
    return payload


def _top_level_failures(model: Mapping[str, Any], scenario_catalog: Mapping[str, Any], scenario_ids: list[str]) -> list[str]:
    failures = []
    if model.get("schema_version") != MODEL_SCHEMA_VERSION:
        failures.append(f"schema_version must be {MODEL_SCHEMA_VERSION}")
    if model.get("collection_mode") not in {"fixture", "real"}:
        failures.append("collection_mode must be fixture or real")
    missing = sorted(set(scenario_ids) - set(scenario_catalog))
    for scenario_id in missing:
        failures.append(f"scenario_id not found: {scenario_id}")
    if len(scenario_ids) != len(set(scenario_ids)):
        failures.append("scenario_ids must be unique")
    return failures


def _phase_failures(
    phases: list[Mapping[str, Any]],
    scenario_ids: list[str],
    scenario_hypotheses: Mapping[str, set[str]],
) -> list[str]:
    failures = []
    if len(phases) < 3:
        failures.append("temporal benchmark requires at least three phases")
    phase_ids = [str(phase.get("id") or "") for phase in phases]
    if len(phase_ids) != len(set(phase_ids)):
        failures.append("phase ids must be unique")
    orders = [int(phase.get("order") or 0) for phase in phases]
    if len(orders) != len(set(orders)):
        failures.append("phase orders must be unique")
    allowed_scenarios = set(scenario_ids)
    allowed_hypotheses = set().union(*scenario_hypotheses.values()) if scenario_hypotheses else set()
    active: set[str] = set()
    previous_start = -1
    for phase in sorted(phases, key=lambda item: int(item.get("order") or 0)):
        phase_id = str(phase.get("id") or "")
        start = int(phase.get("starts_at_seconds") or 0)
        if start < previous_start:
            failures.append(f"phase {phase_id} starts before the prior ordered phase")
        previous_start = start
        unknown_scenarios = sorted(set(_string_list(phase.get("active_scenario_ids", []))) - allowed_scenarios)
        for scenario_id in unknown_scenarios:
            failures.append(f"phase {phase_id} references unknown active_scenario_id: {scenario_id}")
        expected = phase.get("expected_hypotheses", {})
        add = set(_string_list(expected.get("add", []))) if isinstance(expected, dict) else set()
        remove = set(_string_list(expected.get("remove", []))) if isinstance(expected, dict) else set()
        declared_active = set(_string_list(expected.get("active", []))) if isinstance(expected, dict) else set()
        unknown_hypotheses = sorted((add | remove | declared_active) - allowed_hypotheses)
        for hypothesis in unknown_hypotheses:
            failures.append(f"phase {phase_id} references hypothesis outside selected scenarios: {hypothesis}")
        computed_active = (active - remove) | add
        if declared_active != computed_active:
            failures.append(
                f"phase {phase_id} active hypotheses do not match prior active plus add/remove transition"
            )
        active = declared_active
        for symptom in phase.get("delayed_symptoms", []):
            if not isinstance(symptom, dict):
                continue
            appears_after = int(symptom.get("appears_after_seconds") or 0)
            if appears_after < start:
                failures.append(f"phase {phase_id} delayed symptom {symptom.get('id')} appears before phase start")
    return failures


def _causal_link_failures(phases: list[Mapping[str, Any]], causal_links: list[Mapping[str, Any]]) -> list[str]:
    failures = []
    phase_starts = {str(phase.get("id")): int(phase.get("starts_at_seconds") or 0) for phase in phases}
    for link in causal_links:
        source = str(link.get("from_phase") or "")
        target = str(link.get("to_phase") or "")
        if source not in phase_starts:
            failures.append(f"causal link references unknown from_phase: {source}")
            continue
        if target not in phase_starts:
            failures.append(f"causal link references unknown to_phase: {target}")
            continue
        if phase_starts[source] >= phase_starts[target]:
            failures.append(f"causal link must point forward in time: {source} -> {target}")
    if phases and not causal_links:
        failures.append("temporal benchmark requires at least one causal link")
    return failures


def _phase_row(phase: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": str(phase.get("id") or ""),
        "order": int(phase.get("order") or 0),
        "kind": str(phase.get("kind") or ""),
        "starts_at_seconds": int(phase.get("starts_at_seconds") or 0),
        "duration_seconds": int(phase.get("duration_seconds") or 0),
        "active_scenario_ids": _string_list(phase.get("active_scenario_ids", [])),
        "evidence_adapters": _string_list(phase.get("evidence_adapters", [])),
        "expected_hypotheses": copy.deepcopy(phase.get("expected_hypotheses", {})),
        "delayed_symptoms": copy.deepcopy(phase.get("delayed_symptoms", [])),
    }


def _coverage(packages: list[Any], phases: list[dict[str, Any]], causal_links: list[Mapping[str, Any]]) -> dict[str, Any]:
    return {
        "domains": sorted({package.domain for package in packages}),
        "archetypes": sorted({str(package.spec.get("environment_archetype") or "") for package in packages}),
        "phase_kinds": sorted({phase["kind"] for phase in phases if phase.get("kind")}),
        "phase_ids": [phase["id"] for phase in phases],
        "causal_edges": [f"{link.get('from_phase')}->{link.get('to_phase')}" for link in causal_links],
        "evidence_adapters": sorted(
            {adapter for phase in phases for adapter in phase.get("evidence_adapters", []) if adapter}
        ),
    }


def _scenario_hypotheses(packages: list[Any]) -> dict[str, set[str]]:
    return {
        package.name: {str(hypothesis) for hypothesis in package.spec.get("expected_hypotheses", []) if str(hypothesis)}
        for package in packages
    }


def _load_catalog(root: Path) -> list[Any]:
    return [load_scenario_package(path) for path in list_scenario_packages(root)]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]
