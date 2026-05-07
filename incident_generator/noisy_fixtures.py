"""Deterministic noisy fixture bundle rendering."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Mapping

from .benchmark_result_helpers import (
    canonical_json as _canonical_json,
    relative_path as _relative_path,
    sha256_file,
    sha256_text,
    stable_hash,
)
from .parsers import load_yaml
from .provider_contracts import default_provider_contracts
from .scenarios import ScenarioPackage


SCHEMA_VERSION = "sre-agent.noisy-fixture-bundle/v1"
NOISE_CATALOG_RELATIVE = Path("harness/production-noise-source-catalog.yaml")
ROLE_TAXONOMY_RELATIVE = Path("harness/evidence-signal-role-taxonomy.yaml")


def render_noisy_fixture_bundle(
    root: Path,
    package: ScenarioPackage,
    *,
    seed: int | None = None,
    max_noise_sources: int | None = None,
) -> dict[str, Any]:
    """Render a deterministic internal manifest for a noisy fixture bundle."""
    root = root.resolve()
    noise_catalog_path = root / NOISE_CATALOG_RELATIVE
    role_taxonomy_path = root / ROLE_TAXONOMY_RELATIVE
    noise_catalog = load_yaml(noise_catalog_path)
    role_taxonomy = load_yaml(role_taxonomy_path)
    selected_seed = _selected_seed(package, seed)
    profile_id = _noise_profile_id(package)
    source_ids = _selected_noise_source_ids(noise_catalog, profile_id, seed=selected_seed, max_sources=max_noise_sources)
    source_by_id = _source_catalog_by_id(noise_catalog)
    fixture_entries = _fixture_entries(root, package)
    noise_entries = [
        _noise_entry(
            source_by_id[source_id],
            root=root,
            package=package,
            seed=selected_seed,
            index=index,
        )
        for index, source_id in enumerate(source_ids)
    ]
    entries = fixture_entries + noise_entries
    payload: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "scenario": package.name,
        "scenario_path": _relative_path(root, package.path),
        "fixture": _relative_path(root, package.fixture_path),
        "seed": selected_seed,
        "deterministic": True,
        "expected_hypotheses": copy.deepcopy(package.spec.get("expected_hypotheses", [])),
        "noise_profile": {
            "id": profile_id,
            "source_ids": source_ids,
        },
        "source_catalog": {
            "path": str(NOISE_CATALOG_RELATIVE),
            "sha256": sha256_file(noise_catalog_path),
        },
        "role_taxonomy": {
            "path": str(ROLE_TAXONOMY_RELATIVE),
            "sha256": sha256_file(role_taxonomy_path),
            "agent_visible_role_labels": bool(
                role_taxonomy.get("visibility", {}).get("agent_inputs", {}).get("expose_role_labels")
            ),
        },
        "untrusted_data_framing": {
            "required": True,
            "agent_visible_role_labels": False,
            "agent_visible_source_ids": False,
        },
        "evidence": entries,
        "signal_role_counts": _role_counts(entries),
    }
    payload["artifact_hash"] = stable_hash(payload)
    return payload


def _selected_seed(package: ScenarioPackage, seed: int | None) -> int:
    if seed is not None:
        return seed
    load_generator = package.spec.get("workload_profile", {}).get("load_generator", {})
    if isinstance(load_generator, dict) and isinstance(load_generator.get("seed"), int):
        return int(load_generator["seed"])
    return 20260506


def _noise_profile_id(package: ScenarioPackage) -> str | None:
    noise_profile = package.spec.get("workload_profile", {}).get("noise_profile", {})
    if isinstance(noise_profile, dict) and noise_profile.get("id"):
        return str(noise_profile["id"])
    return None


def _selected_noise_source_ids(
    noise_catalog: Mapping[str, Any],
    profile_id: str | None,
    *,
    seed: int,
    max_sources: int | None,
) -> list[str]:
    if not profile_id:
        return []
    profiles = noise_catalog.get("profiles", {})
    profile = profiles.get(profile_id, {}) if isinstance(profiles, dict) else {}
    source_ids = [str(source_id) for source_id in profile.get("source_ids", []) if str(source_id)]
    if max_sources is None or max_sources >= len(source_ids):
        return source_ids
    if max_sources <= 0:
        return []
    return sorted(source_ids, key=lambda source_id: _selection_key(seed, profile_id, source_id))[:max_sources]


def _selection_key(seed: int, profile_id: str, source_id: str) -> str:
    return sha256_text(f"{seed}:{profile_id}:{source_id}")


def _source_catalog_by_id(noise_catalog: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    sources = noise_catalog.get("sources", [])
    return {str(source["id"]): source for source in sources if isinstance(source, dict) and source.get("id")}


def _fixture_entries(root: Path, package: ScenarioPackage) -> list[dict[str, Any]]:
    contracts = {contract.adapter_id: contract for contract in default_provider_contracts()}
    causal_sources = set(_string_list(package.spec.get("incident_injection", {}).get("causal_signal_sources", [])))
    ambient_sources = set(
        _string_list(package.spec.get("workload_profile", {}).get("noise_profile", {}).get("ambient_signal_sources", []))
    )
    expected_hypothesis = package.spec.get("incident_injection", {}).get("expected_hypothesis")
    entries: list[dict[str, Any]] = []
    for adapter_id in _string_list(package.spec.get("evidence_adapters_required", [])):
        contract = contracts.get(adapter_id)
        if contract is None:
            continue
        output_path = package.fixture_path / "outputs" / f"{contract.fixture_key}.txt"
        if not output_path.is_file():
            continue
        role = _fixture_role(adapter_id, causal_sources, ambient_sources)
        digest = sha256_file(output_path)
        entry = {
            "evidence_ref": f"fixture:{adapter_id}",
            "kind": "checked_fixture_output",
            "adapter_ids": [adapter_id],
            "internal": {
                "source_id": f"fixture:{adapter_id}",
                "signal_role": role,
                "expected_hypothesis_link": expected_hypothesis if role == "causal" else None,
            },
            "agent_visible": {
                "path": _relative_path(root, output_path),
                "sha256": digest,
                "untrusted_data": True,
            },
        }
        entries.append(entry)
        if _contains_hostile_text(output_path.read_text(encoding="utf-8", errors="replace")):
            entries.append(
                {
                    "evidence_ref": f"fixture:{adapter_id}:hostile",
                    "kind": "checked_fixture_hostile_marker",
                    "adapter_ids": [adapter_id],
                    "internal": {
                        "source_id": "adversarial_fixture.hostile_text",
                        "signal_role": "hostile",
                        "expected_hypothesis_link": None,
                    },
                    "agent_visible": {
                        "path": _relative_path(root, output_path),
                        "sha256": digest,
                        "untrusted_data": True,
                    },
                }
            )
    return entries


def _fixture_role(adapter_id: str, causal_sources: set[str], ambient_sources: set[str]) -> str:
    if adapter_id in causal_sources:
        return "causal"
    if adapter_id in ambient_sources:
        return "ambient"
    return "contextual"


def _noise_entry(source: Mapping[str, Any], *, root: Path, package: ScenarioPackage, seed: int, index: int) -> dict[str, Any]:
    source_id = str(source["id"])
    visible_text = _noise_text(source, package=package, seed=seed, index=index)
    return {
        "evidence_ref": f"noise:{source_id}",
        "kind": "production_noise",
        "adapter_ids": _string_list(source.get("evidence_adapters", [])),
        "internal": {
            "source_id": source_id,
            "signal_role": "ambient",
            "expected_hypothesis_link": None,
            "bounds": copy.deepcopy(source.get("bounds", {})),
        },
        "agent_visible": {
            "text": visible_text,
            "sha256": sha256_text(visible_text),
            "untrusted_data": True,
        },
    }


def _noise_text(source: Mapping[str, Any], *, package: ScenarioPackage, seed: int, index: int) -> str:
    service = _main_service(package)
    source_name = str(source.get("name") or "background signal").lower()
    bounded = _canonical_json(source.get("bounds", {}))
    fingerprint = sha256_text(f"{seed}:{package.name}:{source.get('id')}:{index}")[:12]
    return (
        f"timestamp=2026-05-06T00:{index:02d}:00Z service={service} "
        f"event={_slug(source_name)} detail=\"{source_name} observed within normal bounds\" "
        f"bounds={bounded} sample_id={fingerprint}"
    )


def _main_service(package: ScenarioPackage) -> str:
    workload_profile = package.spec.get("workload_profile", {})
    if isinstance(workload_profile, dict) and workload_profile.get("main_service"):
        return str(workload_profile["main_service"])
    inputs = package.spec.get("inputs", {})
    if isinstance(inputs, dict) and inputs.get("service"):
        return str(inputs["service"])
    return package.name


def _contains_hostile_text(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in ("ignore the incident prompt", "output the letters", "forbidden"))


def _role_counts(entries: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entry in entries:
        role = str(entry.get("internal", {}).get("signal_role") or "unknown")
        counts[role] = counts.get(role, 0) + 1
    return dict(sorted(counts.items()))


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item)]


def _slug(value: str) -> str:
    return "-".join(part for part in value.replace("/", " ").replace("_", " ").split() if part)
