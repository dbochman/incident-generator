"""Recovery-after-diagnosis benchmark reports."""

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
from .parsers import load_yaml
from .scenarios import load_scenario_package, validate_scenario_package


REPORT_SCHEMA_VERSION = "sre-agent.recovery-after-diagnosis-benchmark-report/v1"
BENCHMARK_SCHEMA_VERSION = "sre-agent.recovery-after-diagnosis-benchmark/v1"
DEFAULT_RECOVERY_BENCHMARK_RELATIVE = Path("harness/recovery-after-diagnosis-benchmark.yaml")
CLASS_3_GATES = {"domain_supervisor", "generalist_supervisor", "human_confirmation"}


def render_recovery_after_diagnosis_benchmark(
    root: Path,
    *,
    benchmark_path: Path | None = None,
) -> dict[str, Any]:
    """Render a semantic report for recovery-after-diagnosis benchmark cases."""
    root = root.resolve()
    benchmark_path = _resolve_path(root, benchmark_path or DEFAULT_RECOVERY_BENCHMARK_RELATIVE)
    benchmark = load_yaml(benchmark_path)
    action_templates = _action_templates_by_id(benchmark.get("action_templates", []))
    case_rows = [
        _case_row(root, case, action_templates)
        for case in benchmark.get("cases", [])
        if isinstance(case, dict)
    ]
    failures = []
    failures.extend(_top_level_failures(benchmark, action_templates, case_rows))
    for template in action_templates.values():
        failures.extend(_action_template_failures(template))
    for row in case_rows:
        failures.extend(row["failures"])
    coverage = _coverage(case_rows, action_templates)
    payload: dict[str, Any] = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "benchmark_schema_version": str(benchmark.get("schema_version") or ""),
        "benchmark_id": str(benchmark.get("benchmark_id") or benchmark_path.stem),
        "benchmark_path": _relative_path(root, benchmark_path),
        "description": str(benchmark.get("description") or ""),
        "collection_mode": str(benchmark.get("collection_mode") or ""),
        "case_count": len(case_rows),
        "safe_dry_run_case_count": sum(
            1 for row in case_rows if row["expected_transition"]["mode"] == "safe_dry_run_plan"
        ),
        "hold_case_count": sum(1 for row in case_rows if row["expected_transition"]["mode"] == "hold_for_more_evidence"),
        "action_template_count": len(action_templates),
        "coverage": coverage,
        "scoring": copy.deepcopy(benchmark.get("scoring", {})),
        "passed": not failures,
        "failures": failures,
        "cases": case_rows,
    }
    payload["artifact_hash"] = _stable_hash(payload)
    return payload


def _top_level_failures(
    benchmark: Mapping[str, Any],
    action_templates: Mapping[str, Mapping[str, Any]],
    case_rows: list[dict[str, Any]],
) -> list[str]:
    failures = []
    if benchmark.get("schema_version") != BENCHMARK_SCHEMA_VERSION:
        failures.append(f"schema_version must be {BENCHMARK_SCHEMA_VERSION}")
    if benchmark.get("collection_mode") not in {"fixture", "real"}:
        failures.append("collection_mode must be fixture or real")
    if len(case_rows) < 2:
        failures.append("recovery-after-diagnosis benchmark requires at least two cases")
    case_ids = [row["id"] for row in case_rows]
    for duplicate in _duplicates(case_ids):
        failures.append(f"duplicate case id: {duplicate}")
    if not action_templates:
        failures.append("recovery-after-diagnosis benchmark requires action_templates")
    return failures


def _action_template_failures(template: Mapping[str, Any]) -> list[str]:
    failures = []
    template_id = str(template.get("id") or "")
    action_class = int(template.get("action_class") or 0)
    if action_class >= 3:
        if template.get("requires_recovery_plan") is not True:
            failures.append(f"action template {template_id} Class 3+ must require recovery plans")
        if template.get("dry_run_available") is not True:
            failures.append(f"action template {template_id} Class 3+ must expose dry-run support")
        missing_gates = sorted(CLASS_3_GATES - set(_string_list(template.get("required_gates", []))))
        for gate in missing_gates:
            failures.append(f"action template {template_id} missing Class 3 gate: {gate}")
        state_preservation = set(_string_list(template.get("state_preservation", [])))
        if not {"before", "after"}.issubset(state_preservation):
            failures.append(f"action template {template_id} Class 3+ must preserve before and after state")
    if action_class == 4:
        failures.append(f"action template {template_id} Class 4 actions are out of benchmark scope")
    if template.get("mutation_type") == "destructive_state_change":
        failures.append(f"action template {template_id} destructive_state_change is out of benchmark scope")
    return failures


def _case_row(
    root: Path,
    case: Mapping[str, Any],
    action_templates: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    scenario_path = _resolve_path(root, Path(str(case.get("scenario") or "")))
    package = load_scenario_package(scenario_path)
    transition = case.get("expected_transition", {}) if isinstance(case.get("expected_transition"), dict) else {}
    diagnosis = case.get("expected_diagnosis", {}) if isinstance(case.get("expected_diagnosis"), dict) else {}
    action_template_id = str(transition.get("action_template_id") or "")
    action_template = action_templates.get(action_template_id, {})
    plan = _load_plan(root, transition)
    plan_sources = _source_refs(plan)
    plan_step_types = _step_types(plan)
    plan_action_ids = _plan_action_ids(plan)
    failures = []
    failures.extend(f"scenario {package.name}: {failure}" for failure in validate_scenario_package(package))
    failures.extend(_case_contract_failures(package, case, diagnosis, transition, action_template, plan))
    row = {
        "id": str(case.get("id") or package.name),
        "scenario": package.name,
        "scenario_path": _relative_path(root, package.path),
        "domain": package.domain,
        "stage": str(case.get("stage") or ""),
        "skill_under_test": _relative_path(root, package.skill_path),
        "fixture": _relative_path(root, package.fixture_path),
        "initial_requires_action_abstention": bool(
            package.spec.get("success_criteria", {}).get("requires_action_abstention")
        ),
        "initial_forbidden_actions": _string_list(package.spec.get("forbidden_actions", [])),
        "expected_diagnosis": {
            "hypothesis": str(diagnosis.get("hypothesis") or ""),
            "confidence_floor": str(diagnosis.get("confidence_floor") or ""),
            "evidence_refs": _string_list(diagnosis.get("evidence_refs", [])),
        },
        "expected_transition": {
            "mode": str(transition.get("mode") or ""),
            "recovery_plan_id": str(transition.get("recovery_plan_id") or ""),
            "plan_fixture": _relative_path(root, _resolve_path(root, Path(str(transition.get("plan_fixture") or ""))))
            if transition.get("plan_fixture")
            else "",
            "action_template_id": action_template_id,
            "action_category": str(action_template.get("category") or ""),
            "action_class": int(transition.get("action_class") or 0),
            "blast_radius_scope": str(action_template.get("blast_radius_scope") or ""),
            "dry_run_required": bool(transition.get("dry_run_required")),
            "mutations_invoked": bool(transition.get("mutations_invoked")),
            "required_gates": _string_list(transition.get("required_gates", [])),
            "required_step_types": _string_list(transition.get("required_step_types", [])),
            "required_state_preservation": _string_list(transition.get("required_state_preservation", [])),
            "preserved_evidence_refs": _string_list(transition.get("preserved_evidence_refs", [])),
            "plan_source_refs": _string_list(transition.get("plan_source_refs", [])),
            "forbidden_actions": _string_list(transition.get("forbidden_actions", [])),
        },
        "plan_summary": {
            "plan_id": str(plan.get("plan_id") or ""),
            "rollback_strategy": str(plan.get("rollback_strategy") or ""),
            "step_types": plan_step_types,
            "action_template_ids": plan_action_ids,
            "source_refs": plan_sources,
            "system_action_state_preservation": _system_action_state_preservation(plan, action_template_id),
        },
        "passed": not failures,
        "failures": failures,
    }
    row["evidence_preservation"] = {
        "preserved_count": len(row["expected_transition"]["preserved_evidence_refs"]),
        "all_preserved_refs_in_diagnosis": set(row["expected_transition"]["preserved_evidence_refs"]).issubset(
            set(row["expected_diagnosis"]["evidence_refs"])
        ),
        "all_preserved_refs_in_scenario": set(row["expected_transition"]["preserved_evidence_refs"]).issubset(
            set(_string_list(package.spec.get("evidence_adapters_required", [])))
        ),
    }
    return row


def _case_contract_failures(
    package: Any,
    case: Mapping[str, Any],
    diagnosis: Mapping[str, Any],
    transition: Mapping[str, Any],
    action_template: Mapping[str, Any],
    plan: Mapping[str, Any],
) -> list[str]:
    failures = []
    case_id = str(case.get("id") or package.name)
    expected_hypothesis = str(diagnosis.get("hypothesis") or "")
    if str(case.get("stage") or "") != "post_diagnosis":
        failures.append(f"case {case_id} must start at post_diagnosis stage")
    if expected_hypothesis not in _string_list(package.spec.get("expected_hypotheses", [])):
        failures.append(f"case {case_id} diagnosis hypothesis not expected by scenario: {expected_hypothesis}")
    scenario_evidence = set(_string_list(package.spec.get("evidence_adapters_required", [])))
    diagnosis_refs = set(_string_list(diagnosis.get("evidence_refs", [])))
    for evidence_ref in sorted(diagnosis_refs - scenario_evidence):
        failures.append(f"case {case_id} diagnosis evidence ref is not required by scenario: {evidence_ref}")
    if not package.spec.get("success_criteria", {}).get("requires_action_abstention"):
        failures.append(f"case {case_id} must preserve initial diagnostic action-abstention scoring")

    action_template_id = str(transition.get("action_template_id") or "")
    if not action_template:
        failures.append(f"case {case_id} references unknown action template: {action_template_id}")
        return failures
    action_class = int(transition.get("action_class") or 0)
    if action_class != int(action_template.get("action_class") or 0):
        failures.append(f"case {case_id} action_class does not match action template {action_template_id}")
    if str(transition.get("mode") or "") == "safe_dry_run_plan":
        failures.extend(_safe_dry_run_failures(case_id, transition, action_template, plan))
    preserved_refs = set(_string_list(transition.get("preserved_evidence_refs", [])))
    for evidence_ref in sorted(preserved_refs - diagnosis_refs):
        failures.append(f"case {case_id} preserved evidence ref was not cited by diagnosis: {evidence_ref}")
    for evidence_ref in sorted(preserved_refs - scenario_evidence):
        failures.append(f"case {case_id} preserved evidence ref is not scenario evidence: {evidence_ref}")
    return failures


def _safe_dry_run_failures(
    case_id: str,
    transition: Mapping[str, Any],
    action_template: Mapping[str, Any],
    plan: Mapping[str, Any],
) -> list[str]:
    failures = []
    action_template_id = str(transition.get("action_template_id") or "")
    if int(transition.get("action_class") or 0) < 3:
        failures.append(f"case {case_id} safe dry-run plan must be Class 3+")
    if transition.get("dry_run_required") is not True:
        failures.append(f"case {case_id} safe dry-run plan must require dry-run")
    if transition.get("mutations_invoked") is not False:
        failures.append(f"case {case_id} safe dry-run plan must keep mutations_invoked false")
    missing_gates = sorted(CLASS_3_GATES - set(_string_list(transition.get("required_gates", []))))
    for gate in missing_gates:
        failures.append(f"case {case_id} safe dry-run plan missing gate: {gate}")
    if action_template.get("requires_recovery_plan") is not True:
        failures.append(f"case {case_id} action template {action_template_id} must require recovery plan")
    if action_template.get("dry_run_available") is not True:
        failures.append(f"case {case_id} action template {action_template_id} must support dry-run")
    if not plan:
        failures.append(f"case {case_id} safe dry-run plan requires plan_fixture")
        return failures
    if str(plan.get("plan_id") or "") != str(transition.get("recovery_plan_id") or ""):
        failures.append(f"case {case_id} plan_fixture plan_id does not match recovery_plan_id")
    plan_action_ids = set(_plan_action_ids(plan))
    if action_template_id not in plan_action_ids:
        failures.append(f"case {case_id} plan_fixture does not include action template {action_template_id}")
    plan_step_types = set(_step_types(plan))
    for step_type in sorted(set(_string_list(transition.get("required_step_types", []))) - plan_step_types):
        failures.append(f"case {case_id} plan_fixture missing step type: {step_type}")
    plan_sources = set(_source_refs(plan))
    for source_ref in sorted(set(_string_list(transition.get("plan_source_refs", []))) - plan_sources):
        failures.append(f"case {case_id} plan_fixture missing source ref: {source_ref}")
    state_preservation = set(_system_action_state_preservation(plan, action_template_id))
    for key in sorted(set(_string_list(transition.get("required_state_preservation", []))) - state_preservation):
        failures.append(f"case {case_id} system action missing state_preservation.{key}")
    return failures


def _load_plan(root: Path, transition: Mapping[str, Any]) -> dict[str, Any]:
    plan_fixture = transition.get("plan_fixture")
    if not plan_fixture:
        return {}
    return load_yaml(_resolve_path(root, Path(str(plan_fixture))))


def _action_templates_by_id(raw_templates: Any) -> dict[str, Mapping[str, Any]]:
    if not isinstance(raw_templates, list):
        return {}
    templates: dict[str, Mapping[str, Any]] = {}
    for template in raw_templates:
        if not isinstance(template, dict):
            continue
        template_id = str(template.get("id") or "")
        if template_id:
            templates[template_id] = template
    return templates


def _coverage(case_rows: list[dict[str, Any]], action_templates: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    modes = Counter(row["expected_transition"]["mode"] for row in case_rows)
    return {
        "domains": sorted({row["domain"] for row in case_rows if row["domain"]}),
        "scenario_ids": sorted({row["scenario"] for row in case_rows}),
        "expected_hypotheses": sorted({row["expected_diagnosis"]["hypothesis"] for row in case_rows}),
        "action_template_ids": sorted(action_templates),
        "action_categories": sorted({str(template.get("category") or "") for template in action_templates.values()}),
        "action_classes": sorted({int(template.get("action_class") or 0) for template in action_templates.values()}),
        "blast_radius_scopes": sorted(
            {str(template.get("blast_radius_scope") or "") for template in action_templates.values()}
        ),
        "transition_modes": dict(sorted(modes.items())),
        "preserved_evidence_refs": sorted(
            {
                evidence_ref
                for row in case_rows
                for evidence_ref in row["expected_transition"]["preserved_evidence_refs"]
            }
        ),
        "plan_fixtures": sorted(
            {
                row["expected_transition"]["plan_fixture"]
                for row in case_rows
                if row["expected_transition"]["plan_fixture"]
            }
        ),
    }


def _step_types(plan: Mapping[str, Any]) -> list[str]:
    return sorted({str(step.get("type") or "") for step in plan.get("steps", []) if isinstance(step, dict)})


def _plan_action_ids(plan: Mapping[str, Any]) -> list[str]:
    return sorted(
        {
            str(step.get("action_template_id") or "")
            for step in plan.get("steps", [])
            if isinstance(step, dict) and step.get("type") == "system_action"
        }
    )


def _source_refs(value: Any) -> list[str]:
    refs: set[str] = set()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            source = node.get("source")
            if source:
                refs.add(str(source))
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return sorted(refs)


def _system_action_state_preservation(plan: Mapping[str, Any], action_template_id: str) -> list[str]:
    keys: set[str] = set()
    for step in plan.get("steps", []):
        if not isinstance(step, dict):
            continue
        if step.get("type") != "system_action" or step.get("action_template_id") != action_template_id:
            continue
        state_preservation = step.get("state_preservation", {})
        if isinstance(state_preservation, dict):
            keys.update(str(key) for key in state_preservation if state_preservation.get(key) is not None)
    return sorted(keys)


def _duplicates(values: list[str]) -> list[str]:
    counts = Counter(values)
    return sorted(value for value, count in counts.items() if count > 1)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]
