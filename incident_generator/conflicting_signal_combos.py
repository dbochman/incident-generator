"""Deterministic conflicting-signal benchmark combo rendering."""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from .parsers import load_yaml


SCHEMA_VERSION = "sre-agent.conflicting-signal-combos/v1"
DEFAULT_CONFLICTING_SIGNAL_COMBOS_RELATIVE = Path("harness/conflicting-signal-combos.yaml")

ALLOWED_SIGNAL_AXES = {
    "deploy_vs_dependency",
    "rollback_vs_dependency",
    "latency_vs_database",
}
ALLOWED_CHECKS = {
    "expected_hypotheses_preserved",
    "competing_hypotheses_visible",
    "composed_confidence_not_high",
    "investigation_terms_present",
    "no_premature_action",
}
CONFIDENCE_RANK = {"low": 1, "medium": 2, "high": 3}


def render_conflicting_signal_combo_report(root: Path, *, combo_path: Path | None = None) -> dict[str, Any]:
    """Render a deterministic report for conflicting-signal benchmark combinations."""
    root = root.resolve()
    combo_path = _resolve_path(root, combo_path or DEFAULT_CONFLICTING_SIGNAL_COMBOS_RELATIVE)
    plan = load_yaml(combo_path)
    combos = [
        _combo_report(root, combo, index=index)
        for index, combo in enumerate(plan.get("combos", []), start=1)
        if isinstance(combo, dict)
    ]
    coverage = _coverage(combos)
    failures = _top_level_failures(plan, combos, coverage)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "combo_set_id": str(plan.get("id") or combo_path.stem),
        "combo_path": _relative_path(root, combo_path),
        "description": str(plan.get("description") or ""),
        "seed": _optional_int(plan.get("seed")),
        "deterministic": plan.get("seed") is not None,
        "required_axes": _string_list(plan.get("required_axes")),
        "required_checks": _string_list(plan.get("required_checks")),
        "combo_count": len(combos),
        "passed_count": sum(1 for combo in combos if combo["passed"]),
        "passed": not failures and all(combo["passed"] for combo in combos),
        "coverage": coverage,
        "failures": failures,
        "combos": combos,
    }
    payload["artifact_hash"] = _stable_hash(payload)
    return payload


def _combo_report(root: Path, combo: Mapping[str, Any], *, index: int) -> dict[str, Any]:
    case_rows = [
        _case_report(root, case, case_index=case_index)
        for case_index, case in enumerate(combo.get("cases", []), start=1)
        if isinstance(case, dict)
    ]
    case_ids = [row["id"] for row in case_rows]
    failures: list[str] = []
    if len(case_rows) < 2:
        failures.append("conflicting-signal combo requires at least two cases")
    duplicates = sorted(case_id for case_id, count in Counter(case_ids).items() if count > 1)
    if duplicates:
        failures.append("duplicate case ids in combo: " + ", ".join(duplicates))
    for row in case_rows:
        failures.extend(f"{row['id']}: {failure}" for failure in row["failures"])

    required_axes = set(_string_list(combo.get("required_axes")))
    unsupported_axes = sorted(required_axes - ALLOWED_SIGNAL_AXES)
    if unsupported_axes:
        failures.append("unsupported combo required axes: " + ", ".join(unsupported_axes))
    missing_axes = sorted(required_axes - {row["signal_axis"] for row in case_rows})
    if missing_axes:
        failures.append("missing combo required axes: " + ", ".join(missing_axes))

    ceiling = str(combo.get("composed_confidence_ceiling") or "medium")
    if ceiling not in CONFIDENCE_RANK:
        failures.append(f"unsupported composed_confidence_ceiling: {ceiling}")

    shared_services = _shared_values(row["target_service"] for row in case_rows)
    expected_hypotheses = sorted({row["expected_hypothesis"] for row in case_rows if row["expected_hypothesis"]})
    competing_hypotheses = sorted({item for row in case_rows for item in row["competing_hypotheses"]})
    missing_competing = sorted(set(competing_hypotheses) - set(expected_hypotheses))
    if missing_competing:
        failures.append("competing hypotheses are not represented by combo cases: " + ", ".join(missing_competing))

    return {
        "id": str(combo.get("id") or f"conflicting-signal-combo-{index:02d}"),
        "description": str(combo.get("description") or ""),
        "combo_size": len(case_rows),
        "domains": sorted({row["domain"] for row in case_rows if row["domain"]}),
        "signal_axes": sorted({row["signal_axis"] for row in case_rows if row["signal_axis"]}),
        "target_services": sorted({row["target_service"] for row in case_rows if row["target_service"]}),
        "shared_services": shared_services,
        "expected_hypotheses": expected_hypotheses,
        "competing_hypotheses": competing_hypotheses,
        "composed_confidence_ceiling": ceiling,
        "required_summary_terms": _string_list(combo.get("required_summary_terms")),
        "required_next_step_terms": sorted({item for row in case_rows for item in row["required_next_step_terms"]}),
        "cases": case_rows,
        "passed": not failures,
        "failures": failures,
    }


def _case_report(root: Path, case: Mapping[str, Any], *, case_index: int) -> dict[str, Any]:
    skill_path = _resolve_path(root, Path(str(case.get("skill") or "")))
    fixture_path = _resolve_path(root, Path(str(case.get("fixture") or "")))
    expected_path = fixture_path / "expected.yaml"
    fixture_meta_path = fixture_path / "fixture.yaml"
    expected: Mapping[str, Any] = {}
    fixture_meta: Mapping[str, Any] = {}
    failures: list[str] = []

    if not skill_path.is_file():
        failures.append(f"skill path does not exist: {_relative_path(root, skill_path)}")
    if not fixture_path.is_dir():
        failures.append(f"fixture path does not exist: {_relative_path(root, fixture_path)}")
    else:
        if not expected_path.is_file():
            failures.append(f"fixture expected.yaml does not exist: {_relative_path(root, expected_path)}")
        else:
            expected = load_yaml(expected_path)
        if fixture_meta_path.is_file():
            fixture_meta = load_yaml(fixture_meta_path)

    signal_axis = str(case.get("signal_axis") or "")
    if signal_axis not in ALLOWED_SIGNAL_AXES:
        failures.append(f"unsupported signal_axis: {signal_axis}")

    expected_hypothesis = str(case.get("expected_hypothesis") or "")
    fixture_primary = str(expected.get("primary_diagnosis_id") or expected.get("diagnosis_id") or "")
    if not expected_hypothesis:
        failures.append("expected_hypothesis is required")
    if expected_hypothesis and fixture_primary and expected_hypothesis != fixture_primary:
        failures.append(
            f"expected_hypothesis {expected_hypothesis} does not match fixture diagnosis id {fixture_primary}"
        )

    competing = _string_list(case.get("competing_hypotheses"))
    if not competing:
        failures.append("competing_hypotheses must be non-empty")
    next_step_terms = _string_list(case.get("required_next_step_terms"))
    if not next_step_terms:
        failures.append("required_next_step_terms must be non-empty")

    target = fixture_meta.get("target", {}) if isinstance(fixture_meta, Mapping) else {}
    target_service = str(target.get("service") or "") if isinstance(target, Mapping) else ""

    return {
        "id": str(case.get("id") or fixture_path.name or f"case-{case_index:02d}"),
        "domain": str(case.get("domain") or ""),
        "signal_axis": signal_axis,
        "skill_under_test": _relative_path(root, skill_path),
        "fixture": _relative_path(root, fixture_path),
        "fixture_primary_diagnosis": fixture_primary,
        "target_service": target_service,
        "expected_hypothesis": expected_hypothesis,
        "competing_hypotheses": competing,
        "required_next_step_terms": next_step_terms,
        "passed": not failures,
        "failures": failures,
    }


def _coverage(combos: list[dict[str, Any]]) -> dict[str, Any]:
    cases = [case for combo in combos for case in combo["cases"]]
    return {
        "combo_sizes": dict(sorted(Counter(str(combo["combo_size"]) for combo in combos).items())),
        "domains": sorted({case["domain"] for case in cases if case["domain"]}),
        "signal_axes": sorted({case["signal_axis"] for case in cases if case["signal_axis"]}),
        "target_services": sorted({case["target_service"] for case in cases if case["target_service"]}),
        "expected_hypotheses": sorted({case["expected_hypothesis"] for case in cases if case["expected_hypothesis"]}),
        "competing_hypothesis_count": sum(len(case["competing_hypotheses"]) for case in cases),
        "required_next_step_term_count": sum(len(case["required_next_step_terms"]) for case in cases),
        "shared_service_combo_count": sum(1 for combo in combos if combo["shared_services"]),
        "confidence_ceiling_counts": dict(sorted(Counter(combo["composed_confidence_ceiling"] for combo in combos).items())),
        "has_all_required_axes_combo": any(set(combo["signal_axes"]) >= ALLOWED_SIGNAL_AXES for combo in combos),
    }


def _top_level_failures(
    plan: Mapping[str, Any],
    combos: list[dict[str, Any]],
    coverage: Mapping[str, Any],
) -> list[str]:
    failures = []
    if not combos:
        failures.append("conflicting-signal combo plan contains no combos")
    required_axes = set(_string_list(plan.get("required_axes")))
    unsupported_axes = sorted(required_axes - ALLOWED_SIGNAL_AXES)
    if unsupported_axes:
        failures.append("unsupported required_axes: " + ", ".join(unsupported_axes))
    missing_axes = sorted(required_axes - set(coverage.get("signal_axes", [])))
    if missing_axes:
        failures.append("missing required signal axes: " + ", ".join(missing_axes))
    required_checks = set(_string_list(plan.get("required_checks")))
    unsupported_checks = sorted(required_checks - ALLOWED_CHECKS)
    if unsupported_checks:
        failures.append("unsupported required checks: " + ", ".join(unsupported_checks))
    if "competing_hypotheses_visible" in required_checks and int(coverage.get("competing_hypothesis_count") or 0) <= 0:
        failures.append("required check competing_hypotheses_visible has no competing hypotheses")
    if "investigation_terms_present" in required_checks and int(coverage.get("required_next_step_term_count") or 0) <= 0:
        failures.append("required check investigation_terms_present has no required next-step terms")
    if "composed_confidence_not_high" in required_checks and not coverage.get("confidence_ceiling_counts"):
        failures.append("required check composed_confidence_not_high has no confidence ceilings")
    if plan.get("require_shared_service_combo") is True and int(coverage.get("shared_service_combo_count") or 0) <= 0:
        failures.append("no combo shares a target service across conflicting cases")
    return failures


def _resolve_path(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relative_path(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return str(path)


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if isinstance(item, str) and item]
    return []


def _shared_values(values: Any) -> list[str]:
    counts = Counter(str(value) for value in values if value)
    return sorted(value for value, count in counts.items() if count > 1)


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


def _stable_hash(payload: Mapping[str, Any]) -> str:
    clean = {key: value for key, value in payload.items() if key != "artifact_hash"}
    encoded = json.dumps(clean, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
