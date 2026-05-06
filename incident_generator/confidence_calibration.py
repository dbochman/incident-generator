"""Confidence calibration benchmark report rendering."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from .parsers import load_yaml


SCHEMA_VERSION = "sre-agent.confidence-calibration-report/v1"
DEFAULT_CONFIDENCE_CALIBRATION_RELATIVE = Path("harness/confidence-calibration-report.yaml")

ALLOWED_AGENT_MODES = {"deterministic", "live_llm_snapshot"}
ALLOWED_EVIDENCE_QUALITIES = {"low", "medium", "high"}
CONFIDENCE_RANK = {"low": 1, "medium": 2, "high": 3}


def render_confidence_calibration_report(
    root: Path,
    *,
    calibration_path: Path | None = None,
) -> dict[str, Any]:
    """Render the checked confidence calibration snapshot."""
    root = root.resolve()
    calibration_path = _resolve_path(root, calibration_path or DEFAULT_CONFIDENCE_CALIBRATION_RELATIVE)
    plan = load_yaml(calibration_path)
    policy, policy_failures = _quality_policy(plan.get("quality_policy", {}))
    cases = [
        _case_report(root, case, policy=policy, case_index=index)
        for index, case in enumerate(plan.get("cases", []), start=1)
        if isinstance(case, dict)
    ]
    coverage = _coverage(cases)
    failures = _top_level_failures(plan, cases, coverage, policy, policy_failures)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "calibration_set_id": str(plan.get("id") or calibration_path.stem),
        "calibration_path": _relative_path(root, calibration_path),
        "description": str(plan.get("description") or ""),
        "seed": _optional_int(plan.get("seed")),
        "deterministic": plan.get("seed") is not None,
        "required_agents": _string_list(plan.get("required_agents")),
        "required_evidence_qualities": _string_list(plan.get("required_evidence_qualities")),
        "quality_policy": policy,
        "live_snapshot": _live_snapshot(plan.get("live_snapshot", {})),
        "case_count": len(cases),
        "observation_count": sum(len(case["observations"]) for case in cases),
        "passed_count": sum(1 for case in cases if case["passed"]),
        "passed": not failures and all(case["passed"] for case in cases),
        "coverage": coverage,
        "failures": failures,
        "cases": cases,
    }
    payload["artifact_hash"] = _stable_hash(payload)
    return payload


def _case_report(
    root: Path,
    case: Mapping[str, Any],
    *,
    policy: Mapping[str, Mapping[str, str]],
    case_index: int,
) -> dict[str, Any]:
    skill_path = _resolve_path(root, Path(str(case.get("skill") or "")))
    fixture_path = _resolve_path(root, Path(str(case.get("fixture") or "")))
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

    evidence_quality = str(case.get("evidence_quality") or "")
    if evidence_quality not in ALLOWED_EVIDENCE_QUALITIES:
        failures.append(f"unsupported evidence_quality: {evidence_quality}")
    policy_row = policy.get(evidence_quality, {})
    target_confidence = str(case.get("target_confidence") or policy_row.get("target_confidence") or "")
    min_confidence = str(case.get("min_confidence") or policy_row.get("min_confidence") or "")
    max_confidence = str(case.get("max_confidence") or policy_row.get("max_confidence") or "")
    failures.extend(_confidence_range_failures(target_confidence, min_confidence, max_confidence))

    expected_hypothesis = str(case.get("expected_hypothesis") or "")
    fixture_primary = _expected_primary(expected)
    if not expected_hypothesis:
        failures.append("expected_hypothesis is required")
    if expected_hypothesis and fixture_primary and expected_hypothesis != fixture_primary:
        failures.append(
            f"expected_hypothesis {expected_hypothesis} does not match fixture diagnosis id {fixture_primary}"
        )

    observations = [
        _observation_report(
            observation,
            expected_hypothesis=expected_hypothesis,
            target_confidence=target_confidence,
            min_confidence=min_confidence,
            max_confidence=max_confidence,
        )
        for observation in case.get("observations", [])
        if isinstance(observation, dict)
    ]
    observed_agents = [row["agent"] for row in observations]
    duplicate_agents = sorted(agent for agent, count in Counter(observed_agents).items() if count > 1)
    if duplicate_agents:
        failures.append("duplicate observation agents: " + ", ".join(duplicate_agents))
    if not observations:
        failures.append("case contains no observations")
    for row in observations:
        failures.extend(f"{row['agent']}: {failure}" for failure in row["failures"])

    return {
        "id": str(case.get("id") or fixture_path.name or f"calibration-case-{case_index:02d}"),
        "description": str(case.get("description") or ""),
        "evidence_quality": evidence_quality,
        "skill_under_test": _relative_path(root, skill_path),
        "fixture": _relative_path(root, fixture_path),
        "fixture_primary_diagnosis": fixture_primary,
        "expected_hypothesis": expected_hypothesis,
        "target_confidence": target_confidence,
        "min_confidence": min_confidence,
        "max_confidence": max_confidence,
        "source_docs": sorted({row["source_doc"] for row in observations if row["source_doc"]}),
        "observations": observations,
        "calibration_flags": _case_flags(observations),
        "passed": not failures,
        "failures": failures,
    }


def _observation_report(
    observation: Mapping[str, Any],
    *,
    expected_hypothesis: str,
    target_confidence: str,
    min_confidence: str,
    max_confidence: str,
) -> dict[str, Any]:
    failures: list[str] = []
    agent = str(observation.get("agent") or "")
    if agent not in ALLOWED_AGENT_MODES:
        failures.append(f"unsupported agent: {agent}")
    confidence = str(observation.get("confidence") or "")
    if confidence not in CONFIDENCE_RANK:
        failures.append(f"unsupported confidence: {confidence}")
    primary = str(observation.get("primary_diagnosis") or "")
    if expected_hypothesis and primary != expected_hypothesis:
        failures.append(f"primary diagnosis {primary} does not match expected {expected_hypothesis}")
    within_range = _within_range(confidence, min_confidence, max_confidence)
    if confidence in CONFIDENCE_RANK and not within_range:
        failures.append(f"confidence {confidence} outside allowed range {min_confidence}..{max_confidence}")
    live_provider_calls = bool(observation.get("live_provider_calls_observed", False))
    if agent == "live_llm_snapshot" and not live_provider_calls:
        failures.append("live_llm_snapshot must record live_provider_calls_observed")
    if agent == "deterministic" and live_provider_calls:
        failures.append("deterministic observation must not record live provider calls")
    if agent == "live_llm_snapshot" and str(observation.get("tier2_status") or "") != "executed":
        failures.append("live_llm_snapshot must record executed Tier 2 status")
    source_doc = str(observation.get("source_doc") or "")
    if not source_doc:
        failures.append("source_doc is required")
    source_fixture = str(observation.get("source_fixture") or "")
    if not source_fixture:
        failures.append("source_fixture is required")

    delta = _confidence_rank(confidence) - _confidence_rank(target_confidence)
    return {
        "agent": agent,
        "primary_diagnosis": primary,
        "confidence": confidence,
        "target_confidence": target_confidence,
        "confidence_delta_from_target": delta,
        "within_range": within_range,
        "target_match": confidence == target_confidence,
        "source_doc": source_doc,
        "source_fixture": source_fixture,
        "live_provider_calls_observed": live_provider_calls,
        "tier2_status": str(observation.get("tier2_status") or ""),
        "passed": not failures,
        "failures": failures,
    }


def _quality_policy(value: Any) -> tuple[dict[str, dict[str, str]], list[str]]:
    failures: list[str] = []
    policy: dict[str, dict[str, str]] = {}
    if not isinstance(value, Mapping):
        return policy, ["quality_policy must be a mapping"]
    for quality, row in value.items():
        quality_name = str(quality)
        if quality_name not in ALLOWED_EVIDENCE_QUALITIES:
            failures.append(f"unsupported quality_policy key: {quality_name}")
            continue
        if not isinstance(row, Mapping):
            failures.append(f"quality_policy {quality_name} must be a mapping")
            continue
        target = str(row.get("target_confidence") or "")
        minimum = str(row.get("min_confidence") or "")
        maximum = str(row.get("max_confidence") or "")
        failures.extend(f"{quality_name}: {failure}" for failure in _confidence_range_failures(target, minimum, maximum))
        policy[quality_name] = {
            "target_confidence": target,
            "min_confidence": minimum,
            "max_confidence": maximum,
        }
    return policy, failures


def _confidence_range_failures(target: str, minimum: str, maximum: str) -> list[str]:
    failures: list[str] = []
    for label, value in (("target_confidence", target), ("min_confidence", minimum), ("max_confidence", maximum)):
        if value not in CONFIDENCE_RANK:
            failures.append(f"unsupported {label}: {value}")
    if all(value in CONFIDENCE_RANK for value in (target, minimum, maximum)):
        if _confidence_rank(minimum) > _confidence_rank(maximum):
            failures.append(f"min_confidence {minimum} exceeds max_confidence {maximum}")
        if not _within_range(target, minimum, maximum):
            failures.append(f"target_confidence {target} outside allowed range {minimum}..{maximum}")
    return failures


def _live_snapshot(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    return {
        "provider": str(value.get("provider") or ""),
        "model": str(value.get("model") or ""),
        "judge_provider": str(value.get("judge_provider") or ""),
        "judge_model": str(value.get("judge_model") or ""),
        "source_index": str(value.get("source_index") or ""),
        "live_provider_calls_observed": bool(value.get("live_provider_calls_observed", False)),
    }


def _coverage(cases: list[dict[str, Any]]) -> dict[str, Any]:
    observations = [observation for case in cases for observation in case["observations"]]
    agent_counts = Counter(observation["agent"] for observation in observations if observation["agent"])
    return {
        "evidence_quality_counts": dict(sorted(Counter(case["evidence_quality"] for case in cases).items())),
        "agent_counts": dict(sorted(agent_counts.items())),
        "confidence_counts_by_agent": _confidence_counts_by_agent(observations),
        "bounded_pass_count": sum(1 for observation in observations if observation["within_range"]),
        "target_match_count": sum(1 for observation in observations if observation["target_match"]),
        "over_target_count": sum(1 for observation in observations if observation["confidence_delta_from_target"] > 0),
        "under_target_count": sum(1 for observation in observations if observation["confidence_delta_from_target"] < 0),
        "live_snapshot_count": sum(1 for observation in observations if observation["agent"] == "live_llm_snapshot"),
        "live_provider_call_observed_count": sum(
            1
            for observation in observations
            if observation["agent"] == "live_llm_snapshot" and observation["live_provider_calls_observed"]
        ),
        "source_doc_count": len({observation["source_doc"] for observation in observations if observation["source_doc"]}),
    }


def _confidence_counts_by_agent(observations: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    counts: dict[str, Counter[str]] = {}
    for observation in observations:
        agent = observation["agent"]
        counts.setdefault(agent, Counter())[observation["confidence"]] += 1
    return {agent: dict(sorted(counter.items())) for agent, counter in sorted(counts.items())}


def _case_flags(observations: list[dict[str, Any]]) -> list[str]:
    flags: list[str] = []
    for observation in observations:
        if not observation["within_range"]:
            flags.append(f"{observation['agent']}:out_of_range")
        elif observation["confidence_delta_from_target"] > 0:
            flags.append(f"{observation['agent']}:over_target_within_range")
        elif observation["confidence_delta_from_target"] < 0:
            flags.append(f"{observation['agent']}:under_target_within_range")
    return flags


def _top_level_failures(
    plan: Mapping[str, Any],
    cases: list[dict[str, Any]],
    coverage: Mapping[str, Any],
    policy: Mapping[str, Mapping[str, str]],
    policy_failures: list[str],
) -> list[str]:
    failures = list(policy_failures)
    if not cases:
        failures.append("confidence calibration report contains no cases")
    required_qualities = set(_string_list(plan.get("required_evidence_qualities")))
    unsupported_qualities = sorted(required_qualities - ALLOWED_EVIDENCE_QUALITIES)
    if unsupported_qualities:
        failures.append("unsupported required_evidence_qualities: " + ", ".join(unsupported_qualities))
    missing_policy = sorted(required_qualities - set(policy))
    if missing_policy:
        failures.append("missing quality_policy entries: " + ", ".join(missing_policy))
    quality_counts = coverage.get("evidence_quality_counts", {})
    missing_quality_cases = sorted(required_qualities - set(quality_counts))
    if missing_quality_cases:
        failures.append("missing calibration cases for qualities: " + ", ".join(missing_quality_cases))
    required_agents = set(_string_list(plan.get("required_agents")))
    unsupported_agents = sorted(required_agents - ALLOWED_AGENT_MODES)
    if unsupported_agents:
        failures.append("unsupported required_agents: " + ", ".join(unsupported_agents))
    agent_counts = coverage.get("agent_counts", {})
    missing_agents = sorted(required_agents - set(agent_counts))
    if missing_agents:
        failures.append("missing required agents: " + ", ".join(missing_agents))
    if "live_llm_snapshot" in required_agents:
        live_count = int(coverage.get("live_snapshot_count") or 0)
        live_call_count = int(coverage.get("live_provider_call_observed_count") or 0)
        if live_count <= 0:
            failures.append("live_llm_snapshot has no observations")
        elif live_call_count != live_count:
            failures.append("not all live_llm_snapshot observations record live provider calls")
    for case in cases:
        case_agents = {observation["agent"] for observation in case["observations"]}
        missing_case_agents = sorted(required_agents - case_agents)
        if missing_case_agents:
            failures.append(f"{case['id']}: missing required agents: " + ", ".join(missing_case_agents))
    return failures


def _expected_primary(expected: Mapping[str, Any]) -> str:
    return str(
        expected.get("primary_diagnosis_id")
        or expected.get("diagnosis_id")
        or expected.get("expected_primary_diagnosis")
        or ""
    )


def _within_range(confidence: str, minimum: str, maximum: str) -> bool:
    rank = _confidence_rank(confidence)
    return _confidence_rank(minimum) <= rank <= _confidence_rank(maximum)


def _confidence_rank(value: str) -> int:
    return CONFIDENCE_RANK.get(value, 0)


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
