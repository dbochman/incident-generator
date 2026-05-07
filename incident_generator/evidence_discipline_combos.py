"""Deterministic missing-evidence and red-herring benchmark combo rendering."""

from __future__ import annotations

import copy
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from .benchmark_result_helpers import (
    relative_path as _relative_path,
    resolve_path as _resolve_path,
    stable_hash as _stable_hash,
)
from .noisy_partial_failures import DEFAULT_PACK_RELATIVE, render_noisy_partial_failure_pack
from .parsers import load_yaml


SCHEMA_VERSION = "sre-agent.evidence-discipline-combos/v1"
DEFAULT_EVIDENCE_DISCIPLINE_COMBOS_RELATIVE = Path("harness/missing-evidence-red-herring-combos.yaml")

ALLOWED_CASE_TYPES = {"noisy_partial_variant", "fixture"}
ALLOWED_DISCIPLINES = {
    "missing_evidence",
    "red_herring",
    "abstention",
    "unknown_hypothesis",
}
ALLOWED_CHECKS = {
    "expected_hypothesis_preserved",
    "forbidden_hypotheses_absent",
    "unknown_preserved",
    "action_abstention",
    "next_step_terms_present",
}


def render_evidence_discipline_combo_report(root: Path, *, combo_path: Path | None = None) -> dict[str, Any]:
    """Render a deterministic report for evidence-discipline benchmark combinations."""
    root = root.resolve()
    combo_path = _resolve_path(root, combo_path or DEFAULT_EVIDENCE_DISCIPLINE_COMBOS_RELATIVE)
    plan = load_yaml(combo_path)
    pack_path = _resolve_path(root, Path(str(plan.get("partial_failure_pack") or DEFAULT_PACK_RELATIVE)))
    seed = _optional_int(plan.get("seed"))
    pack_report = render_noisy_partial_failure_pack(root, pack_path=pack_path, seed=seed)
    variants_by_id = {str(row["id"]): row for row in pack_report.get("variants", [])}
    combos = [
        _combo_report(root, combo, variants_by_id=variants_by_id, index=index)
        for index, combo in enumerate(plan.get("combos", []), start=1)
        if isinstance(combo, dict)
    ]
    coverage = _coverage(combos)
    failures = _top_level_failures(plan, pack_report, combos, coverage)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "combo_set_id": str(plan.get("id") or combo_path.stem),
        "combo_path": _relative_path(root, combo_path),
        "description": str(plan.get("description") or ""),
        "seed": seed,
        "deterministic": seed is not None,
        "partial_failure_pack": _relative_path(root, pack_path),
        "partial_failure_pack_hash": pack_report.get("artifact_hash"),
        "required_disciplines": _string_list(plan.get("required_disciplines")),
        "required_case_types": _string_list(plan.get("required_case_types")),
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


def _combo_report(
    root: Path,
    combo: Mapping[str, Any],
    *,
    variants_by_id: Mapping[str, Mapping[str, Any]],
    index: int,
) -> dict[str, Any]:
    case_rows = [
        _case_report(root, case, variants_by_id=variants_by_id, case_index=case_index)
        for case_index, case in enumerate(combo.get("cases", []), start=1)
        if isinstance(case, dict)
    ]
    case_ids = [row["id"] for row in case_rows]
    failures: list[str] = []
    if len(case_rows) < 2:
        failures.append("evidence-discipline combo requires at least two cases")
    duplicates = sorted(case_id for case_id, count in Counter(case_ids).items() if count > 1)
    if duplicates:
        failures.append("duplicate case ids in combo: " + ", ".join(duplicates))
    for row in case_rows:
        failures.extend(f"{row['id']}: {failure}" for failure in row["failures"])
    required_disciplines = set(_string_list(combo.get("required_disciplines")))
    missing_disciplines = sorted(required_disciplines - {discipline for row in case_rows for discipline in row["disciplines"]})
    if missing_disciplines:
        failures.append("missing combo required disciplines: " + ", ".join(missing_disciplines))

    return {
        "id": str(combo.get("id") or f"evidence-discipline-combo-{index:02d}"),
        "description": str(combo.get("description") or ""),
        "combo_size": len(case_rows),
        "case_types": sorted({row["case_type"] for row in case_rows if row["case_type"]}),
        "domains": sorted({row["domain"] for row in case_rows if row["domain"]}),
        "disciplines": sorted({discipline for row in case_rows for discipline in row["disciplines"]}),
        "failure_modes": sorted({row["failure_mode"] for row in case_rows if row["failure_mode"]}),
        "expected_hypotheses": sorted({row["expected_hypothesis"] for row in case_rows if row["expected_hypothesis"]}),
        "forbidden_hypotheses": sorted({item for row in case_rows for item in row["forbidden_hypotheses"]}),
        "requires_unknown": any(row["requires_unknown"] for row in case_rows),
        "requires_action_abstention": any(row["requires_action_abstention"] for row in case_rows),
        "required_next_step_terms": sorted({item for row in case_rows for item in row["required_next_step_terms"]}),
        "cases": case_rows,
        "passed": not failures,
        "failures": failures,
    }


def _case_report(
    root: Path,
    case: Mapping[str, Any],
    *,
    variants_by_id: Mapping[str, Mapping[str, Any]],
    case_index: int,
) -> dict[str, Any]:
    case_type = str(case.get("type") or "")
    failures = []
    if case_type not in ALLOWED_CASE_TYPES:
        failures.append(f"unsupported case type: {case_type}")
    disciplines = _string_list(case.get("disciplines"))
    unsupported_disciplines = sorted(set(disciplines) - ALLOWED_DISCIPLINES)
    if unsupported_disciplines:
        failures.append("unsupported disciplines: " + ", ".join(unsupported_disciplines))
    if not disciplines:
        failures.append("disciplines must be non-empty")

    if case_type == "noisy_partial_variant":
        row = variants_by_id.get(str(case.get("variant") or ""))
        if row is None:
            failures.append(f"unknown noisy partial-failure variant: {case.get('variant')}")
            return _empty_case(case, case_index=case_index, case_type=case_type, failures=failures)
        failures.extend(str(failure) for failure in row.get("failures", []))
        expected = str(case.get("expected_hypothesis") or row.get("expected_hypothesis") or "")
        if expected != str(row.get("expected_hypothesis") or ""):
            failures.append(
                f"expected_hypothesis {expected} does not match noisy partial-failure variant {row.get('expected_hypothesis')}"
            )
        return {
            "id": str(case.get("id") or row["id"]),
            "case_type": case_type,
            "variant": str(row["id"]),
            "domain": str(row.get("domain") or ""),
            "scenario": str(row.get("scenario") or ""),
            "scenario_path": str(row.get("scenario_path") or ""),
            "skill_under_test": str(row.get("skill_under_test") or ""),
            "fixture": str(row.get("fixture") or ""),
            "failure_mode": str(row.get("failure_mode") or ""),
            "disciplines": disciplines,
            "expected_hypothesis": expected,
            "forbidden_hypotheses": _combined_string_list(
                row.get("forbidden_hypotheses", []),
                case.get("forbidden_hypotheses", []),
            ),
            "requires_unknown": bool(case.get("requires_unknown")),
            "requires_action_abstention": bool(case.get("requires_action_abstention")),
            "required_next_step_terms": _string_list(case.get("required_next_step_terms")),
            "passed": not failures,
            "failures": failures,
        }

    if case_type == "fixture":
        skill_path = _resolve_path(root, Path(str(case.get("skill") or "")))
        fixture_path = _resolve_path(root, Path(str(case.get("fixture") or "")))
        expected_path = fixture_path / "expected.yaml"
        expected_payload: Mapping[str, Any] = {}
        if not skill_path.is_file():
            failures.append(f"skill path does not exist: {_relative_path(root, skill_path)}")
        if not fixture_path.is_dir():
            failures.append(f"fixture path does not exist: {_relative_path(root, fixture_path)}")
        elif not expected_path.is_file():
            failures.append(f"fixture expected.yaml does not exist: {_relative_path(root, expected_path)}")
        else:
            expected_payload = load_yaml(expected_path)
        expected = str(case.get("expected_hypothesis") or "")
        fixture_primary = str(expected_payload.get("primary_diagnosis_id") or "")
        if not expected:
            failures.append("expected_hypothesis is required")
        if expected and fixture_primary and expected != fixture_primary:
            failures.append(
                f"expected_hypothesis {expected} does not match fixture primary_diagnosis_id {fixture_primary}"
            )
        return {
            "id": str(case.get("id") or fixture_path.name or f"case-{case_index:02d}"),
            "case_type": case_type,
            "variant": "",
            "domain": str(case.get("domain") or ""),
            "scenario": "",
            "scenario_path": "",
            "skill_under_test": _relative_path(root, skill_path),
            "fixture": _relative_path(root, fixture_path),
            "failure_mode": str(case.get("failure_mode") or ""),
            "disciplines": disciplines,
            "expected_hypothesis": expected,
            "forbidden_hypotheses": _string_list(case.get("forbidden_hypotheses")),
            "requires_unknown": bool(case.get("requires_unknown")),
            "requires_action_abstention": bool(case.get("requires_action_abstention")),
            "required_next_step_terms": _string_list(case.get("required_next_step_terms")),
            "passed": not failures,
            "failures": failures,
        }

    return _empty_case(case, case_index=case_index, case_type=case_type, failures=failures)


def _empty_case(
    case: Mapping[str, Any],
    *,
    case_index: int,
    case_type: str,
    failures: list[str],
) -> dict[str, Any]:
    return {
        "id": str(case.get("id") or f"case-{case_index:02d}"),
        "case_type": case_type,
        "variant": str(case.get("variant") or ""),
        "domain": str(case.get("domain") or ""),
        "scenario": "",
        "scenario_path": "",
        "skill_under_test": str(case.get("skill") or ""),
        "fixture": str(case.get("fixture") or ""),
        "failure_mode": str(case.get("failure_mode") or ""),
        "disciplines": _string_list(case.get("disciplines")),
        "expected_hypothesis": str(case.get("expected_hypothesis") or ""),
        "forbidden_hypotheses": _string_list(case.get("forbidden_hypotheses")),
        "requires_unknown": bool(case.get("requires_unknown")),
        "requires_action_abstention": bool(case.get("requires_action_abstention")),
        "required_next_step_terms": _string_list(case.get("required_next_step_terms")),
        "passed": False,
        "failures": failures,
    }


def _coverage(combos: list[dict[str, Any]]) -> dict[str, Any]:
    cases = [case for combo in combos for case in combo["cases"]]
    return {
        "combo_sizes": dict(sorted(Counter(str(combo["combo_size"]) for combo in combos).items())),
        "case_types": sorted({case["case_type"] for case in cases if case["case_type"]}),
        "disciplines": sorted({discipline for case in cases for discipline in case["disciplines"]}),
        "domains": sorted({case["domain"] for case in cases if case["domain"]}),
        "failure_modes": sorted({case["failure_mode"] for case in cases if case["failure_mode"]}),
        "expected_hypotheses": sorted({case["expected_hypothesis"] for case in cases if case["expected_hypothesis"]}),
        "forbidden_hypothesis_count": sum(len(case["forbidden_hypotheses"]) for case in cases),
        "required_next_step_term_count": sum(len(case["required_next_step_terms"]) for case in cases),
        "requires_unknown_count": sum(1 for case in cases if case["requires_unknown"]),
        "requires_action_abstention_count": sum(1 for case in cases if case["requires_action_abstention"]),
        "has_missing_and_red_herring_combo": any(
            {"missing_evidence", "red_herring"}.issubset(set(combo["disciplines"])) for combo in combos
        ),
        "has_unknown_combo": any("unknown_hypothesis" in combo["disciplines"] for combo in combos),
    }


def _top_level_failures(
    plan: Mapping[str, Any],
    pack_report: Mapping[str, Any],
    combos: list[dict[str, Any]],
    coverage: Mapping[str, Any],
) -> list[str]:
    failures = []
    if not pack_report.get("passed"):
        failures.append("referenced noisy partial-failure pack did not pass")
    if not combos:
        failures.append("evidence-discipline combo plan contains no combos")
    required_disciplines = set(_string_list(plan.get("required_disciplines")))
    missing_disciplines = sorted(required_disciplines - set(coverage.get("disciplines", [])))
    if missing_disciplines:
        failures.append("missing required disciplines: " + ", ".join(missing_disciplines))
    required_case_types = set(_string_list(plan.get("required_case_types")))
    missing_case_types = sorted(required_case_types - set(coverage.get("case_types", [])))
    if missing_case_types:
        failures.append("missing required case types: " + ", ".join(missing_case_types))
    required_checks = set(_string_list(plan.get("required_checks")))
    unsupported_checks = sorted(required_checks - ALLOWED_CHECKS)
    if unsupported_checks:
        failures.append("unsupported required checks: " + ", ".join(unsupported_checks))
    if "forbidden_hypotheses_absent" in required_checks and int(coverage.get("forbidden_hypothesis_count") or 0) <= 0:
        failures.append("required check forbidden_hypotheses_absent has no forbidden hypotheses")
    if "unknown_preserved" in required_checks and int(coverage.get("requires_unknown_count") or 0) <= 0:
        failures.append("required check unknown_preserved has no unknown-preservation cases")
    if "action_abstention" in required_checks and int(coverage.get("requires_action_abstention_count") or 0) <= 0:
        failures.append("required check action_abstention has no action-abstention cases")
    if "next_step_terms_present" in required_checks and int(coverage.get("required_next_step_term_count") or 0) <= 0:
        failures.append("required check next_step_terms_present has no required next-step terms")
    if plan.get("require_combo_with_missing_and_red_herring") is True and not coverage.get(
        "has_missing_and_red_herring_combo"
    ):
        failures.append("no combo contains both missing_evidence and red_herring disciplines")
    if plan.get("require_unknown_case") is True and not coverage.get("has_unknown_combo"):
        failures.append("no combo contains an unknown_hypothesis discipline")
    return failures


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value if isinstance(item, str) and item]
    return []


def _combined_string_list(*values: Any) -> list[str]:
    combined: list[str] = []
    seen = set()
    for value in values:
        for item in _string_list(value):
            if item not in seen:
                seen.add(item)
                combined.append(item)
    return combined


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None
