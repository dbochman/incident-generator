"""Deterministic adversarial benchmark combo rendering."""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from .parsers import load_yaml


SCHEMA_VERSION = "sre-agent.adversarial-benchmark-combos/v1"
DEFAULT_ADVERSARIAL_COMBOS_RELATIVE = Path("harness/adversarial-benchmark-combos.yaml")
ALLOWED_EVIDENCE_CHANNELS = {"kubernetes_event", "linux_journal", "service_log"}


def render_adversarial_combo_report(root: Path, *, combo_path: Path | None = None) -> dict[str, Any]:
    """Render a deterministic report for prompt-injection benchmark combinations."""
    root = root.resolve()
    combo_path = _resolve_path(root, combo_path or DEFAULT_ADVERSARIAL_COMBOS_RELATIVE)
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
        "required_channels": _string_list(plan.get("required_channels")),
        "framing_requirements": copy.deepcopy(plan.get("framing_requirements", {})),
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
    scenario_rows = [
        _scenario_report(root, scenario, scenario_index=scenario_index)
        for scenario_index, scenario in enumerate(combo.get("scenarios", []), start=1)
        if isinstance(scenario, dict)
    ]
    scenario_ids = [row["id"] for row in scenario_rows]
    failures: list[str] = []
    if len(scenario_rows) < 2:
        failures.append("adversarial combo requires at least two scenarios")
    duplicates = sorted(item for item, count in Counter(scenario_ids).items() if count > 1)
    if duplicates:
        failures.append("duplicate scenario ids in combo: " + ", ".join(duplicates))
    for row in scenario_rows:
        failures.extend(f"{row['id']}: {failure}" for failure in row["failures"])
    evidence_channels = sorted({row["evidence_channel"] for row in scenario_rows if row["evidence_channel"]})
    forbidden_outputs = sorted({token for row in scenario_rows for token in row["forbidden_outputs"]})
    expected_hypotheses = sorted({row["expected_hypothesis"] for row in scenario_rows if row["expected_hypothesis"]})
    return {
        "id": str(combo.get("id") or f"adversarial-combo-{index:02d}"),
        "description": str(combo.get("description") or ""),
        "combo_size": len(scenario_rows),
        "domains": sorted({row["domain"] for row in scenario_rows if row["domain"]}),
        "evidence_channels": evidence_channels,
        "expected_hypotheses": expected_hypotheses,
        "forbidden_outputs": forbidden_outputs,
        "forbidden_output_count": len(forbidden_outputs),
        "scenarios": scenario_rows,
        "passed": not failures,
        "failures": failures,
    }


def _scenario_report(root: Path, scenario: Mapping[str, Any], *, scenario_index: int) -> dict[str, Any]:
    skill_path = _resolve_path(root, Path(str(scenario.get("skill") or "")))
    fixture_path = _resolve_path(root, Path(str(scenario.get("fixture") or "")))
    expected_path = fixture_path / "expected.yaml"
    expected: Mapping[str, Any] = {}
    failures: list[str] = []
    if not skill_path.is_file():
        failures.append(f"skill path does not exist: {_relative_path(root, skill_path)}")
    if not fixture_path.is_dir():
        failures.append(f"fixture path does not exist: {_relative_path(root, fixture_path)}")
    elif not expected_path.is_file():
        failures.append(f"fixture expected.yaml does not exist: {_relative_path(root, expected_path)}")
    else:
        expected = load_yaml(expected_path)

    evidence_channel = str(scenario.get("evidence_channel") or "")
    if evidence_channel not in ALLOWED_EVIDENCE_CHANNELS:
        failures.append(f"unsupported evidence_channel: {evidence_channel}")
    expected_hypothesis = str(scenario.get("expected_hypothesis") or "")
    fixture_primary = str(expected.get("primary_diagnosis_id") or "")
    if expected_hypothesis and fixture_primary and expected_hypothesis != fixture_primary:
        failures.append(
            f"expected_hypothesis {expected_hypothesis} does not match fixture primary_diagnosis_id {fixture_primary}"
        )
    if not expected_hypothesis:
        failures.append("expected_hypothesis is required")
    forbidden_outputs = _string_list(expected.get("forbidden_output"))
    if not forbidden_outputs:
        failures.append("fixture must define forbidden_output guards")

    return {
        "id": str(scenario.get("id") or fixture_path.name or f"scenario-{scenario_index:02d}"),
        "domain": str(scenario.get("domain") or ""),
        "evidence_channel": evidence_channel,
        "skill_under_test": _relative_path(root, skill_path),
        "fixture": _relative_path(root, fixture_path),
        "expected_hypothesis": expected_hypothesis,
        "fixture_primary_diagnosis": fixture_primary,
        "forbidden_outputs": forbidden_outputs,
        "passed": not failures,
        "failures": failures,
    }


def _coverage(combos: list[dict[str, Any]]) -> dict[str, Any]:
    scenario_rows = [scenario for combo in combos for scenario in combo["scenarios"]]
    size_counts = Counter(str(combo["combo_size"]) for combo in combos)
    return {
        "combo_sizes": dict(sorted(size_counts.items())),
        "domains": sorted({row["domain"] for row in scenario_rows if row["domain"]}),
        "evidence_channels": sorted({row["evidence_channel"] for row in scenario_rows if row["evidence_channel"]}),
        "expected_hypotheses": sorted(
            {row["expected_hypothesis"] for row in scenario_rows if row["expected_hypothesis"]}
        ),
        "unique_fixture_count": len({row["fixture"] for row in scenario_rows}),
        "forbidden_output_count": sum(len(row["forbidden_outputs"]) for row in scenario_rows),
        "has_all_channels_combo": any(
            set(combo["evidence_channels"]) >= ALLOWED_EVIDENCE_CHANNELS for combo in combos
        ),
    }


def _top_level_failures(
    plan: Mapping[str, Any],
    combos: list[dict[str, Any]],
    coverage: Mapping[str, Any],
) -> list[str]:
    failures = []
    required_channels = set(_string_list(plan.get("required_channels")))
    unsupported_required = sorted(required_channels - ALLOWED_EVIDENCE_CHANNELS)
    if unsupported_required:
        failures.append("unsupported required_channels: " + ", ".join(unsupported_required))
    missing_channels = sorted(required_channels - set(coverage.get("evidence_channels", [])))
    if missing_channels:
        failures.append("missing required evidence channels: " + ", ".join(missing_channels))
    if required_channels and not coverage.get("has_all_channels_combo"):
        failures.append("no combo contains all required evidence channels")
    if not combos:
        failures.append("adversarial combo plan contains no combos")

    framing = plan.get("framing_requirements", {})
    if not isinstance(framing, Mapping):
        failures.append("framing_requirements must be a mapping")
    else:
        if framing.get("agent_visible_role_labels") is not False:
            failures.append("framing_requirements.agent_visible_role_labels must be false")
        if framing.get("agent_visible_source_ids") is not False:
            failures.append("framing_requirements.agent_visible_source_ids must be false")
        if framing.get("require_forbidden_output_absent") is not True:
            failures.append("framing_requirements.require_forbidden_output_absent must be true")
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
