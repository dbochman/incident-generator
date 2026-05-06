"""Deterministic noisy smoke report rendering."""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .noisy_fixtures import render_noisy_fixture_bundle
from .parsers import load_yaml
from .scenarios import load_scenario_package, stand_up_incident_environment, validate_scenario_package


SCHEMA_VERSION = "sre-agent.noisy-smoke-report/v1"
DEFAULT_SMOKE_RELATIVE = Path("harness/noisy-checkout-vertical-smoke.yaml")


def render_noisy_smoke_report(
    root: Path,
    *,
    smoke_path: Path | None = None,
    seed: int | None = None,
    max_noise_sources: int | None = None,
) -> dict[str, Any]:
    """Render a deterministic fixture-mode noisy smoke report."""
    root = root.resolve()
    smoke_path = _resolve_path(root, smoke_path or DEFAULT_SMOKE_RELATIVE)
    smoke = load_yaml(smoke_path)
    selected_seed = seed if seed is not None else _optional_int(smoke.get("seed"))
    selected_max_noise_sources = max_noise_sources if max_noise_sources is not None else _optional_int(
        smoke.get("max_noise_sources")
    )
    rows = [
        _scenario_report(
            root,
            smoke,
            entry,
            seed=selected_seed,
            max_noise_sources=selected_max_noise_sources,
            index=index,
        )
        for index, entry in enumerate(smoke.get("scenarios", []), start=1)
        if isinstance(entry, dict)
    ]
    coverage = _coverage(rows)
    failures = _top_level_failures(smoke, rows, coverage)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "smoke_id": str(smoke.get("id") or smoke_path.stem),
        "smoke_path": _relative_path(root, smoke_path),
        "target": copy.deepcopy(smoke.get("target", {})),
        "seed": selected_seed,
        "max_noise_sources": selected_max_noise_sources,
        "deterministic": True,
        "scenario_count": len(rows),
        "passed_count": sum(1 for row in rows if row["passed"]),
        "passed": not failures and all(row["passed"] for row in rows),
        "coverage": coverage,
        "failures": failures,
        "scenarios": rows,
    }
    payload["artifact_hash"] = _stable_hash(payload)
    return payload


def _scenario_report(
    root: Path,
    smoke: Mapping[str, Any],
    entry: Mapping[str, Any],
    *,
    seed: int | None,
    max_noise_sources: int | None,
    index: int,
) -> dict[str, Any]:
    scenario_path = _resolve_path(root, Path(str(entry.get("path", ""))))
    package = load_scenario_package(scenario_path)
    bundle = render_noisy_fixture_bundle(root, package, seed=seed, max_noise_sources=max_noise_sources)
    fixture_result = stand_up_incident_environment(
        package,
        collection_mode="fixture",
        incident_session_id=f"{smoke.get('id') or 'noisy-smoke'}-{index}",
    )
    workload_profile = package.spec.get("workload_profile", {})
    incident_injection = package.spec.get("incident_injection", {})
    expected_hypothesis = str(entry.get("expected_hypothesis") or incident_injection.get("expected_hypothesis") or "")
    expected_noise_profile = str(entry.get("expected_noise_profile") or "")
    failures = []
    failures.extend(validate_scenario_package(package))
    failures.extend(
        _scenario_contract_failures(
            package,
            smoke,
            expected_hypothesis=expected_hypothesis,
            expected_noise_profile=expected_noise_profile,
        )
    )
    if fixture_result.get("blocked") or not fixture_result.get("generated"):
        failures.append("fixture replay did not generate")
    if expected_hypothesis and expected_hypothesis not in bundle.get("expected_hypotheses", []):
        failures.append(f"expected hypothesis missing from noisy bundle: {expected_hypothesis}")
    if not _causal_role_links_expected_hypothesis(bundle, expected_hypothesis):
        failures.append(f"no causal evidence role links expected hypothesis: {expected_hypothesis}")
    if not any(item.get("kind") == "production_noise" for item in bundle.get("evidence", [])):
        failures.append("no production noise entries rendered")
    if bundle.get("untrusted_data_framing", {}).get("agent_visible_role_labels"):
        failures.append("agent-visible role labels are exposed")
    if bundle.get("untrusted_data_framing", {}).get("agent_visible_source_ids"):
        failures.append("agent-visible source ids are exposed")

    return {
        "scenario": package.name,
        "scenario_path": _relative_path(root, package.path),
        "domain": package.domain,
        "fixture": _relative_path(root, package.fixture_path),
        "skill_under_test": _relative_path(root, package.skill_path),
        "expected_hypothesis": expected_hypothesis,
        "observed_expected_hypothesis": expected_hypothesis in bundle.get("expected_hypotheses", []),
        "fixture_replay_generated": bool(fixture_result.get("generated") and not fixture_result.get("blocked")),
        "workload_profile": {
            "id": str(workload_profile.get("id") or "") if isinstance(workload_profile, dict) else "",
            "main_service": str(workload_profile.get("main_service") or "") if isinstance(workload_profile, dict) else "",
            "noise_profile_id": bundle.get("noise_profile", {}).get("id"),
        },
        "incident_injection": {
            "kind": str(incident_injection.get("kind") or "") if isinstance(incident_injection, dict) else "",
            "starts_after_warmup": bool(incident_injection.get("starts_after_warmup"))
            if isinstance(incident_injection, dict)
            else False,
            "causal_signal_sources": copy.deepcopy(incident_injection.get("causal_signal_sources", []))
            if isinstance(incident_injection, dict)
            else [],
        },
        "noisy_fixture": {
            "schema_version": bundle.get("schema_version"),
            "artifact_hash": bundle.get("artifact_hash"),
            "source_ids": copy.deepcopy(bundle.get("noise_profile", {}).get("source_ids", [])),
            "signal_role_counts": copy.deepcopy(bundle.get("signal_role_counts", {})),
            "evidence_count": len(bundle.get("evidence", [])),
        },
        "passed": not failures,
        "failures": failures,
    }


def _scenario_contract_failures(
    package: Any,
    smoke: Mapping[str, Any],
    *,
    expected_hypothesis: str,
    expected_noise_profile: str,
) -> list[str]:
    failures = []
    target = smoke.get("target", {})
    workload_profile = package.spec.get("workload_profile", {})
    incident_injection = package.spec.get("incident_injection", {})
    if not isinstance(workload_profile, dict):
        return ["workload_profile is missing"]
    if not isinstance(incident_injection, dict):
        return ["incident_injection is missing"]
    target_service = str(target.get("main_service") or "") if isinstance(target, dict) else ""
    if target_service and workload_profile.get("main_service") != target_service:
        failures.append(f"main service mismatch: expected {target_service}, got {workload_profile.get('main_service')}")
    target_warmup = target.get("warmup_seconds") if isinstance(target, dict) else None
    if target_warmup is not None and workload_profile.get("warmup_seconds") != target_warmup:
        failures.append(f"warmup_seconds mismatch: expected {target_warmup}, got {workload_profile.get('warmup_seconds')}")
    noise_profile = workload_profile.get("noise_profile", {})
    if expected_noise_profile and isinstance(noise_profile, dict) and noise_profile.get("id") != expected_noise_profile:
        failures.append(f"noise profile mismatch: expected {expected_noise_profile}, got {noise_profile.get('id')}")
    if incident_injection.get("expected_hypothesis") != expected_hypothesis:
        failures.append(
            "incident_injection expected hypothesis mismatch: "
            f"expected {expected_hypothesis}, got {incident_injection.get('expected_hypothesis')}"
        )
    if incident_injection.get("expected_hypothesis") not in package.spec.get("expected_hypotheses", []):
        failures.append("incident_injection expected hypothesis is not listed in expected_hypotheses")
    if not incident_injection.get("starts_after_warmup"):
        failures.append("incident injection does not start after warm-up")
    return failures


def _causal_role_links_expected_hypothesis(bundle: Mapping[str, Any], expected_hypothesis: str) -> bool:
    for entry in bundle.get("evidence", []):
        if not isinstance(entry, dict):
            continue
        internal = entry.get("internal", {})
        if (
            isinstance(internal, dict)
            and internal.get("signal_role") == "causal"
            and internal.get("expected_hypothesis_link") == expected_hypothesis
        ):
            return True
    return False


def _coverage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "domains": sorted({row["domain"] for row in rows if row.get("domain")}),
        "main_services": sorted(
            {row["workload_profile"]["main_service"] for row in rows if row.get("workload_profile", {}).get("main_service")}
        ),
        "workload_profile_ids": sorted(
            {row["workload_profile"]["id"] for row in rows if row.get("workload_profile", {}).get("id")}
        ),
        "noise_profiles": sorted(
            {
                row["workload_profile"]["noise_profile_id"]
                for row in rows
                if row.get("workload_profile", {}).get("noise_profile_id")
            }
        ),
        "source_ids": sorted(
            {
                source_id
                for row in rows
                for source_id in row.get("noisy_fixture", {}).get("source_ids", [])
                if source_id
            }
        ),
        "expected_hypotheses": sorted({row["expected_hypothesis"] for row in rows if row.get("expected_hypothesis")}),
        "incident_kinds": sorted(
            {
                row["incident_injection"]["kind"]
                for row in rows
                if row.get("incident_injection", {}).get("kind")
            }
        ),
    }


def _top_level_failures(smoke: Mapping[str, Any], rows: list[dict[str, Any]], coverage: Mapping[str, Any]) -> list[str]:
    failures = []
    if not rows:
        failures.append("smoke plan contains no scenarios")
    for profile in _string_list(smoke.get("required_noise_profiles", [])):
        if profile not in coverage.get("noise_profiles", []):
            failures.append(f"required noise profile missing: {profile}")
    for source_id in _string_list(smoke.get("required_noise_source_ids", [])):
        if source_id not in coverage.get("source_ids", []):
            failures.append(f"required noise source missing: {source_id}")
    return failures


def _resolve_path(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _relative_path(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root))
    except ValueError:
        return str(path)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _stable_hash(payload: Mapping[str, Any]) -> str:
    clean = {key: value for key, value in payload.items() if key != "artifact_hash"}
    return hashlib.sha256(json.dumps(clean, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
