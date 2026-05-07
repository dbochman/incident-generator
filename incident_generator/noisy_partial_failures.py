"""Deterministic noisy partial-failure pack rendering."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any, Mapping

from .benchmark_result_helpers import (
    relative_path as _relative_path,
    resolve_path as _resolve_path,
    sha256_text,
    stable_hash,
)
from .noisy_fixtures import NOISE_CATALOG_RELATIVE, render_noisy_fixture_bundle
from .parsers import load_yaml
from .scenarios import load_scenario_package, validate_scenario_package


SCHEMA_VERSION = "sre-agent.noisy-partial-failure-pack-report/v1"
DEFAULT_PACK_RELATIVE = Path("harness/noisy-partial-failure-pack.yaml")
FAILURE_MODES = {
    "partial_seed_success",
    "missing_wait_for_evidence",
    "degraded_but_not_down",
    "unrelated_noisy_evidence",
}
ROLE_VALUES = {"causal", "contextual", "ambient", "red_herring", "hostile"}


def render_noisy_partial_failure_pack(
    root: Path,
    *,
    pack_path: Path | None = None,
    seed: int | None = None,
    max_noise_sources: int | None = None,
) -> dict[str, Any]:
    """Render a deterministic report for noisy partial-failure benchmark variants."""
    root = root.resolve()
    pack_path = _resolve_path(root, pack_path or DEFAULT_PACK_RELATIVE)
    pack = load_yaml(pack_path)
    selected_seed = seed if seed is not None else _optional_int(pack.get("seed"))
    selected_max_noise_sources = max_noise_sources if max_noise_sources is not None else _optional_int(
        pack.get("max_noise_sources")
    )
    rows = [
        _variant_report(
            root,
            pack,
            variant,
            seed=selected_seed,
            max_noise_sources=selected_max_noise_sources,
        )
        for variant in pack.get("variants", [])
        if isinstance(variant, dict)
    ]
    coverage = _coverage(rows)
    failures = _top_level_failures(pack, rows, coverage)
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "pack_id": str(pack.get("id") or pack_path.stem),
        "pack_path": _relative_path(root, pack_path),
        "target": copy.deepcopy(pack.get("target", {})),
        "seed": selected_seed,
        "max_noise_sources": selected_max_noise_sources,
        "deterministic": True,
        "variant_count": len(rows),
        "passed_count": sum(1 for row in rows if row["passed"]),
        "passed": not failures and all(row["passed"] for row in rows),
        "coverage": coverage,
        "failures": failures,
        "variants": rows,
    }
    payload["artifact_hash"] = stable_hash(payload)
    return payload


def build_noisy_partial_failure_variant_entries(
    root: Path,
    package: Any,
    variant: Mapping[str, Any],
    *,
    seed: int | None = None,
) -> list[dict[str, Any]]:
    """Build internal variant evidence entries to append alongside a noisy fixture."""
    root = root.resolve()
    selected_seed = seed if seed is not None else 20260506
    source_catalog = _source_catalog_by_id(load_yaml(root / NOISE_CATALOG_RELATIVE))
    entries: list[dict[str, Any]] = []
    variant_id = str(variant.get("id") or package.name)
    failure_mode = str(variant.get("failure_mode") or "")

    partial_seed = variant.get("partial_seed", {})
    if isinstance(partial_seed, dict) and partial_seed:
        entries.append(
            _variant_entry(
                variant_id,
                kind="partial_seed_result",
                role="ambient",
                source_id="variant.partial_seed_result",
                adapter_ids=_string_list(partial_seed.get("adapter_ids")) or ["incident.timeline"],
                text=_agent_visible_text(
                    partial_seed,
                    default=(
                        "timestamp=2026-05-06T00:20:00Z service="
                        f"{_main_service(package)} event=setup-note "
                        "detail=\"background setup completed with one tolerated side task unavailable\""
                    ),
                ),
            )
        )

    wait_for = variant.get("wait_for_evidence", {})
    if isinstance(wait_for, dict) and wait_for:
        entries.append(
            _variant_entry(
                variant_id,
                kind="missing_wait_for_evidence",
                role="ambient",
                source_id="variant.missing_wait_for_evidence",
                adapter_ids=_string_list(wait_for.get("adapter_ids")) or ["service.slo_status"],
                text=_agent_visible_text(
                    wait_for,
                    default=(
                        "timestamp=2026-05-06T00:21:00Z service="
                        f"{_main_service(package)} event=observation-gap "
                        "detail=\"one symptom wait sample was unavailable; use captured request and trace evidence\""
                    ),
                ),
            )
        )

    degraded = variant.get("degraded_symptom", {})
    if isinstance(degraded, dict) and degraded:
        entries.append(
            _variant_entry(
                variant_id,
                kind="degraded_but_not_down",
                role="ambient",
                source_id="variant.degraded_but_not_down",
                adapter_ids=_string_list(degraded.get("adapter_ids")) or ["service.slo_status", "pagerduty.escalation_state"],
                text=_agent_visible_text(
                    degraded,
                    default=(
                        "timestamp=2026-05-06T00:22:00Z service="
                        f"{_main_service(package)} event=release-watch "
                        "detail=\"low-volume degradation stayed below outage and rollback thresholds\""
                    ),
                ),
            )
        )

    unrelated = variant.get("unrelated_noise", {})
    if isinstance(unrelated, dict):
        for index, source_id in enumerate(_string_list(unrelated.get("source_ids"))):
            source = source_catalog.get(source_id, {})
            entries.append(
                _variant_entry(
                    variant_id,
                    kind="unrelated_noisy_evidence",
                    role="red_herring",
                    source_id=f"variant.unrelated_noise.{source_id}",
                    adapter_ids=_string_list(unrelated.get("adapter_ids"))
                    or _string_list(source.get("evidence_adapters")),
                    text=_agent_visible_text(
                        unrelated,
                        index=index,
                        default=_unrelated_noise_text(source, package=package, seed=selected_seed, index=index),
                    ),
                )
            )

    if not entries and failure_mode:
        entries.append(
            _variant_entry(
                variant_id,
                kind=failure_mode,
                role="ambient",
                source_id=f"variant.{failure_mode}",
                adapter_ids=["incident.timeline"],
                text=(
                    "timestamp=2026-05-06T00:23:00Z service="
                    f"{_main_service(package)} event=benchmark-variant detail=\"fixture-mode variant marker recorded\""
                ),
            )
        )
    return entries


def _variant_report(
    root: Path,
    pack: Mapping[str, Any],
    variant: Mapping[str, Any],
    *,
    seed: int | None,
    max_noise_sources: int | None,
) -> dict[str, Any]:
    scenario_path = _resolve_path(root, Path(str(variant.get("scenario", ""))))
    package = load_scenario_package(scenario_path)
    bundle = render_noisy_fixture_bundle(root, package, seed=seed, max_noise_sources=max_noise_sources)
    variant_entries = build_noisy_partial_failure_variant_entries(root, package, variant, seed=seed)
    combined_entries = list(bundle.get("evidence", [])) + variant_entries
    signal_role_counts = _role_counts(combined_entries)
    expected_hypothesis = str(variant.get("expected_hypothesis") or "")
    failure_mode = str(variant.get("failure_mode") or "")
    failures = []
    failures.extend(validate_scenario_package(package))
    failures.extend(
        _variant_contract_failures(
            package,
            variant,
            bundle,
            signal_role_counts,
            expected_hypothesis=expected_hypothesis,
            failure_mode=failure_mode,
        )
    )
    leaks = _agent_visible_metadata_leaks(combined_entries)
    if leaks:
        failures.extend(leaks)

    return {
        "id": str(variant.get("id") or package.name),
        "scenario": package.name,
        "scenario_path": _relative_path(root, package.path),
        "domain": package.domain,
        "failure_mode": failure_mode,
        "expected_hypothesis": expected_hypothesis,
        "forbidden_hypotheses": _string_list(variant.get("false_attribution_guards", {}).get("forbidden_hypotheses", [])),
        "fixture": _relative_path(root, package.fixture_path),
        "skill_under_test": _relative_path(root, package.skill_path),
        "workload_profile": {
            "id": str(package.spec.get("workload_profile", {}).get("id") or ""),
            "main_service": str(package.spec.get("workload_profile", {}).get("main_service") or ""),
            "noise_profile_id": bundle.get("noise_profile", {}).get("id"),
        },
        "seed_result": copy.deepcopy(variant.get("partial_seed", {})),
        "wait_for_evidence": copy.deepcopy(variant.get("wait_for_evidence", {})),
        "degraded_symptom": copy.deepcopy(variant.get("degraded_symptom", {})),
        "unrelated_noise": copy.deepcopy(variant.get("unrelated_noise", {})),
        "noisy_fixture": {
            "schema_version": bundle.get("schema_version"),
            "artifact_hash": bundle.get("artifact_hash"),
            "source_ids": copy.deepcopy(bundle.get("noise_profile", {}).get("source_ids", [])),
            "base_signal_role_counts": copy.deepcopy(bundle.get("signal_role_counts", {})),
            "combined_signal_role_counts": signal_role_counts,
            "variant_evidence_count": len(variant_entries),
            "evidence_count": len(combined_entries),
        },
        "passed": not failures,
        "failures": failures,
    }


def _variant_contract_failures(
    package: Any,
    variant: Mapping[str, Any],
    bundle: Mapping[str, Any],
    signal_role_counts: Mapping[str, int],
    *,
    expected_hypothesis: str,
    failure_mode: str,
) -> list[str]:
    failures = []
    if failure_mode not in FAILURE_MODES:
        failures.append(f"unsupported failure mode: {failure_mode}")
    if expected_hypothesis not in package.spec.get("expected_hypotheses", []):
        failures.append(f"expected hypothesis is not declared by scenario: {expected_hypothesis}")
    if expected_hypothesis not in bundle.get("expected_hypotheses", []):
        failures.append(f"expected hypothesis missing from noisy fixture: {expected_hypothesis}")
    expected_noise_profile = str(variant.get("expected_noise_profile") or "")
    if expected_noise_profile and bundle.get("noise_profile", {}).get("id") != expected_noise_profile:
        failures.append(
            f"noise profile mismatch: expected {expected_noise_profile}, got {bundle.get('noise_profile', {}).get('id')}"
        )
    if not any(entry.get("kind") == "production_noise" for entry in bundle.get("evidence", [])):
        failures.append("base noisy fixture has no production noise")
    if signal_role_counts.get("ambient", 0) <= 0:
        failures.append("variant pack has no ambient signal role")
    if failure_mode == "partial_seed_success":
        failures.extend(_partial_seed_failures(variant.get("partial_seed", {})))
    if failure_mode == "missing_wait_for_evidence":
        failures.extend(_missing_wait_for_failures(variant.get("wait_for_evidence", {})))
    if failure_mode == "degraded_but_not_down":
        failures.extend(_degraded_symptom_failures(variant.get("degraded_symptom", {})))
    if failure_mode == "unrelated_noisy_evidence":
        if signal_role_counts.get("red_herring", 0) <= 0:
            failures.append("unrelated noisy evidence variant has no red_herring signal role")
        if not _string_list(variant.get("unrelated_noise", {}).get("source_ids", [])):
            failures.append("unrelated noisy evidence variant must list source_ids")
    return failures


def _partial_seed_failures(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["partial_seed must be a mapping"]
    failures = []
    if value.get("status") != "partial":
        failures.append("partial_seed.status must be partial")
    if not _string_list(value.get("succeeded", [])):
        failures.append("partial_seed.succeeded must be non-empty")
    if not _string_list(value.get("failed", [])):
        failures.append("partial_seed.failed must be non-empty")
    if value.get("tolerated") is not True:
        failures.append("partial_seed.tolerated must be true")
    return failures


def _missing_wait_for_failures(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["wait_for_evidence must be a mapping"]
    failures = []
    if value.get("status") != "missing":
        failures.append("wait_for_evidence.status must be missing")
    if not _string_list(value.get("missing_sources", [])):
        failures.append("wait_for_evidence.missing_sources must be non-empty")
    return failures


def _degraded_symptom_failures(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return ["degraded_symptom must be a mapping"]
    failures = []
    if value.get("symptom_state") != "degraded":
        failures.append("degraded_symptom.symptom_state must be degraded")
    if value.get("outage_state") == "down":
        failures.append("degraded_symptom.outage_state must not be down")
    if value.get("requires_action_abstention") is not True:
        failures.append("degraded_symptom.requires_action_abstention must be true")
    return failures


def _coverage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "domains": sorted({row["domain"] for row in rows if row.get("domain")}),
        "failure_modes": sorted({row["failure_mode"] for row in rows if row.get("failure_mode")}),
        "internal_roles": sorted(
            {role for row in rows for role in row.get("noisy_fixture", {}).get("combined_signal_role_counts", {}) if role}
        ),
        "main_services": sorted(
            {row["workload_profile"]["main_service"] for row in rows if row.get("workload_profile", {}).get("main_service")}
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
    }


def _top_level_failures(pack: Mapping[str, Any], rows: list[dict[str, Any]], coverage: Mapping[str, Any]) -> list[str]:
    failures = []
    if not rows:
        failures.append("partial-failure pack contains no variants")
    for mode in _string_list(pack.get("required_failure_modes", [])):
        if mode not in coverage.get("failure_modes", []):
            failures.append(f"required failure mode missing: {mode}")
    for role in _string_list(pack.get("required_internal_roles", [])):
        if role not in coverage.get("internal_roles", []):
            failures.append(f"required internal role missing: {role}")
    return failures


def _variant_entry(
    variant_id: str,
    *,
    kind: str,
    role: str,
    source_id: str,
    adapter_ids: list[str],
    text: str,
) -> dict[str, Any]:
    return {
        "evidence_ref": f"variant:{variant_id}:{kind}",
        "kind": kind,
        "adapter_ids": adapter_ids,
        "internal": {
            "source_id": source_id,
            "signal_role": role,
            "expected_hypothesis_link": None,
        },
        "agent_visible": {
            "text": text,
            "sha256": sha256_text(text),
            "untrusted_data": True,
        },
    }


def _agent_visible_text(value: Mapping[str, Any], *, default: str, index: int | None = None) -> str:
    texts = value.get("agent_visible_text")
    if isinstance(texts, list) and index is not None and index < len(texts):
        return str(texts[index])
    if isinstance(texts, str) and texts:
        return texts
    return default


def _unrelated_noise_text(source: Mapping[str, Any], *, package: Any, seed: int, index: int) -> str:
    source_name = str(source.get("name") or "background signal").lower()
    fingerprint = sha256_text(f"{seed}:{package.name}:{source.get('id')}:{index}:red-herring")[:12]
    return (
        f"timestamp=2026-05-06T00:{30 + index:02d}:00Z service={_main_service(package)} "
        f"event={_slug(source_name)} detail=\"{source_name} observed outside the incident correlation window\" "
        f"sample_id={fingerprint}"
    )


def _agent_visible_metadata_leaks(entries: list[dict[str, Any]]) -> list[str]:
    failures = []
    for entry in entries:
        internal = entry.get("internal", {})
        visible = json.dumps(entry.get("agent_visible", {}), sort_keys=True)
        source_id = str(internal.get("source_id") or "")
        if source_id and source_id in visible:
            failures.append(f"agent-visible evidence leaks source id: {entry.get('evidence_ref')}")
        role = str(internal.get("signal_role") or "")
        if role in ROLE_VALUES and f'"{role}"' in visible:
            failures.append(f"agent-visible evidence leaks signal role: {entry.get('evidence_ref')}")
    return failures


def _source_catalog_by_id(noise_catalog: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    sources = noise_catalog.get("sources", [])
    return {str(source["id"]): source for source in sources if isinstance(source, dict) and source.get("id")}


def _main_service(package: Any) -> str:
    workload_profile = package.spec.get("workload_profile", {})
    if isinstance(workload_profile, dict) and workload_profile.get("main_service"):
        return str(workload_profile["main_service"])
    inputs = package.spec.get("inputs", {})
    if isinstance(inputs, dict) and inputs.get("service"):
        return str(inputs["service"])
    return package.name


def _role_counts(entries: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in entries:
        role = str(entry.get("internal", {}).get("signal_role") or "unknown")
        counts[role] = counts.get(role, 0) + 1
    return dict(sorted(counts.items()))




def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else None


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _slug(value: str) -> str:
    return "-".join(part for part in value.replace("/", " ").replace("_", " ").split() if part)
