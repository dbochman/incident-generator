"""Deterministic benchmark preview renderers."""

from __future__ import annotations

import copy
import hashlib
import itertools
import json
import random
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from .parsers import load_yaml
from .scenarios import combination_compatibility_report, list_scenario_packages, load_scenario_package


TRIPLE_FIXTURE_SCHEMA_VERSION = "sre-agent.triple-benchmark-fixture-preview/v1"
DEFAULT_TRIPLE_PREVIEW_RELATIVE = Path("harness/triple-benchmark-fixture-preview.yaml")
PAIR_FIXTURE_SCHEMA_VERSION = "sre-agent.random-pair-fixture-preview/v1"
DEFAULT_PAIR_PREVIEW_RELATIVE = Path("harness/random-pair-fixture-preview.yaml")


def render_triple_benchmark_fixture_preview(
    root: Path,
    *,
    preview_path: Path | None = None,
    seed: int | None = None,
    selected_count: int | None = None,
) -> dict[str, Any]:
    """Render a fixed-seed fixture-mode triple benchmark preview."""
    root = root.resolve()
    preview_path = _resolve_path(root, preview_path or DEFAULT_TRIPLE_PREVIEW_RELATIVE)
    preview = load_yaml(preview_path)
    selected_seed = seed if seed is not None else _optional_int(preview.get("seed"))
    requested_count = selected_count if selected_count is not None else _optional_int(preview.get("selected_count"))
    combination_size = _optional_int(preview.get("combination_size")) or 3
    collection_mode = str(preview.get("collection_mode") or "fixture")
    scenario_paths = [_resolve_path(root, Path(path)) for path in _string_list(preview.get("scenario_pool", []))]
    packages = [load_scenario_package(path) for path in scenario_paths]
    candidate_reports = _candidate_reports(packages, combination_size=combination_size, collection_mode=collection_mode)
    compatible_reports = [report for report in candidate_reports if report["compatible"]]
    failures = _contract_failures(
        preview,
        packages,
        candidate_reports,
        compatible_reports,
        collection_mode=collection_mode,
        combination_size=combination_size,
        selected_seed=selected_seed,
        requested_count=requested_count,
    )
    selected_reports: list[dict[str, Any]] = []
    if not failures:
        selected_reports = _select_reports(compatible_reports, count=int(requested_count), seed=int(selected_seed))
    selected_rows = [
        _selected_row(root, report, index=index, preview_id=str(preview.get("id") or preview_path.stem))
        for index, report in enumerate(selected_reports, start=1)
    ]
    coverage = _coverage(packages, selected_rows)
    failures.extend(_coverage_failures(preview, coverage))
    payload: dict[str, Any] = {
        "schema_version": TRIPLE_FIXTURE_SCHEMA_VERSION,
        "preview_id": str(preview.get("id") or preview_path.stem),
        "preview_path": _relative_path(root, preview_path),
        "description": str(preview.get("description") or ""),
        "seed": selected_seed,
        "deterministic": selected_seed is not None,
        "collection_mode": collection_mode,
        "combination_size": combination_size,
        "requested_count": requested_count,
        "scenario_pool_count": len(packages),
        "candidate_pool": {
            "count": len(candidate_reports),
            "included_count": len(compatible_reports),
            "rejected_count": len(candidate_reports) - len(compatible_reports),
            "combination_size": combination_size,
            "compatibility_mode": collection_mode,
            "reason_counts": _reason_counts(candidate_reports),
        },
        "selected_count": len(selected_rows),
        "passed_count": sum(1 for row in selected_rows if row["compatible"]),
        "passed": not failures and all(row["compatible"] for row in selected_rows),
        "coverage": coverage,
        "failures": failures,
        "selected": selected_rows,
    }
    payload["artifact_hash"] = _stable_hash(payload)
    return payload


def render_random_pair_fixture_preview(
    root: Path,
    *,
    preview_path: Path | None = None,
    seed: int | None = None,
    selected_count: int | None = None,
) -> dict[str, Any]:
    """Render a fixed-seed no-startup preview of real-compatible random pairs."""
    root = root.resolve()
    preview_path = _resolve_path(root, preview_path or DEFAULT_PAIR_PREVIEW_RELATIVE)
    preview = load_yaml(preview_path)
    selected_seed = seed if seed is not None else _optional_int(preview.get("seed"))
    requested_count = selected_count if selected_count is not None else _optional_int(preview.get("selected_count"))
    combination_size = _optional_int(preview.get("combination_size")) or 2
    compatibility_mode = str(preview.get("compatibility_mode") or "real")
    archetype = str(preview.get("archetype") or "kind")
    packages = _packages_for_archetype(root, archetype=archetype, mode=compatibility_mode)
    candidate_reports = _candidate_reports(packages, combination_size=combination_size, collection_mode=compatibility_mode)
    compatible_reports = [report for report in candidate_reports if report["compatible"]]
    failures = _pair_contract_failures(
        preview,
        packages,
        candidate_reports,
        compatible_reports,
        compatibility_mode=compatibility_mode,
        combination_size=combination_size,
        selected_seed=selected_seed,
        requested_count=requested_count,
        archetype=archetype,
    )
    selected_reports: list[dict[str, Any]] = []
    if not failures:
        selected_reports = _select_reports(compatible_reports, count=int(requested_count), seed=int(selected_seed))
    selected_rows = [
        _selected_row(
            root,
            report,
            index=index,
            preview_id=str(preview.get("id") or preview_path.stem),
            combination_label="pair",
        )
        for index, report in enumerate(selected_reports, start=1)
    ]
    coverage = _coverage(packages, selected_rows)
    failures.extend(_coverage_failures(preview, coverage))
    payload: dict[str, Any] = {
        "schema_version": PAIR_FIXTURE_SCHEMA_VERSION,
        "preview_id": str(preview.get("id") or preview_path.stem),
        "preview_path": _relative_path(root, preview_path),
        "description": str(preview.get("description") or ""),
        "seed": selected_seed,
        "deterministic": selected_seed is not None,
        "preview_mode": str(preview.get("preview_mode") or ""),
        "compatibility_mode": compatibility_mode,
        "archetype": archetype,
        "combination_size": combination_size,
        "requested_count": requested_count,
        "scenario_pool_count": len(packages),
        "candidate_pool": {
            "count": len(candidate_reports),
            "included_count": len(compatible_reports),
            "rejected_count": len(candidate_reports) - len(compatible_reports),
            "combination_size": combination_size,
            "compatibility_mode": compatibility_mode,
            "reason_counts": _reason_counts(candidate_reports),
        },
        "selected_count": len(selected_rows),
        "passed_count": sum(1 for row in selected_rows if row["compatible"]),
        "passed": not failures and all(row["compatible"] for row in selected_rows),
        "coverage": coverage,
        "failures": failures,
        "selected": selected_rows,
    }
    payload["artifact_hash"] = _stable_hash(payload)
    return payload


def _candidate_reports(
    packages: list[Any],
    *,
    combination_size: int,
    collection_mode: str,
) -> list[dict[str, Any]]:
    sorted_packages = sorted(packages, key=lambda package: str(package.path))
    return [
        combination_compatibility_report(list(candidate), mode=collection_mode)
        for candidate in itertools.combinations(sorted_packages, combination_size)
    ]


def _packages_for_archetype(root: Path, *, archetype: str, mode: str) -> list[Any]:
    packages = []
    for path in list_scenario_packages(root):
        package = load_scenario_package(path)
        axes = package.spec.get("variant_axes", {})
        collection_modes = axes.get("collection_mode", []) if isinstance(axes, dict) else []
        if mode not in collection_modes:
            continue
        if str(package.spec.get("environment_archetype") or "") != archetype:
            continue
        packages.append(package)
    return sorted(packages, key=lambda package: package.name)


def _pair_contract_failures(
    preview: Mapping[str, Any],
    packages: list[Any],
    candidate_reports: list[dict[str, Any]],
    compatible_reports: list[dict[str, Any]],
    *,
    compatibility_mode: str,
    combination_size: int,
    selected_seed: int | None,
    requested_count: int | None,
    archetype: str,
) -> list[str]:
    failures = []
    if compatibility_mode != "real":
        failures.append(f"random pair preview requires real compatibility_mode, got {compatibility_mode}")
    if combination_size != 2:
        failures.append(f"random pair preview requires combination_size 2, got {combination_size}")
    if archetype != "kind":
        failures.append(f"random pair preview requires kind archetype, got {archetype}")
    if selected_seed is None:
        failures.append("random pair preview requires a fixed seed")
    if requested_count is None or requested_count <= 0:
        failures.append("random pair preview requires positive selected_count")
    if not packages:
        failures.append("random pair preview scenario pool is empty")
    if requested_count is not None and requested_count > len(compatible_reports):
        failures.append(
            f"requested {requested_count} pairs, but only {len(compatible_reports)} real-compatible pairs exist"
        )
    if not candidate_reports and packages:
        failures.append("scenario pool cannot satisfy a real-compatible pair")
    expected_pool_count = _optional_int(preview.get("expected_scenario_pool_count"))
    if expected_pool_count is not None and expected_pool_count != len(packages):
        failures.append(f"expected scenario_pool_count {expected_pool_count}, got {len(packages)}")
    expected_candidate_count = _optional_int(preview.get("expected_candidate_count"))
    if expected_candidate_count is not None and expected_candidate_count != len(candidate_reports):
        failures.append(f"expected candidate count {expected_candidate_count}, got {len(candidate_reports)}")
    expected_rejected_count = _optional_int(preview.get("expected_rejected_count"))
    rejected_count = len(candidate_reports) - len(compatible_reports)
    if expected_rejected_count is not None and expected_rejected_count != rejected_count:
        failures.append(f"expected rejected count {expected_rejected_count}, got {rejected_count}")
    return failures


def _contract_failures(
    preview: Mapping[str, Any],
    packages: list[Any],
    candidate_reports: list[dict[str, Any]],
    compatible_reports: list[dict[str, Any]],
    *,
    collection_mode: str,
    combination_size: int,
    selected_seed: int | None,
    requested_count: int | None,
) -> list[str]:
    failures = []
    if collection_mode != "fixture":
        failures.append(f"triple benchmark preview requires fixture collection_mode, got {collection_mode}")
    if combination_size != 3:
        failures.append(f"triple benchmark preview requires combination_size 3, got {combination_size}")
    if selected_seed is None:
        failures.append("triple benchmark preview requires a fixed seed")
    if requested_count is None or requested_count <= 0:
        failures.append("triple benchmark preview requires positive selected_count")
    if not packages:
        failures.append("triple benchmark preview scenario_pool is empty")
    if requested_count is not None and requested_count > len(compatible_reports):
        failures.append(
            f"requested {requested_count} triples, but only {len(compatible_reports)} fixture-compatible triples exist"
        )
    scenario_ids = [package.name for package in packages]
    duplicate_ids = sorted(name for name, count in Counter(scenario_ids).items() if count > 1)
    for duplicate_id in duplicate_ids:
        failures.append(f"duplicate scenario id in scenario_pool: {duplicate_id}")
    if not candidate_reports and packages:
        failures.append("scenario_pool cannot satisfy a fixture-mode triple")
    for required in _string_list(preview.get("required_scenario_ids", [])):
        if required not in scenario_ids:
            failures.append(f"required scenario id missing from pool: {required}")
    return failures


def _select_reports(reports: list[dict[str, Any]], *, count: int, seed: int) -> list[dict[str, Any]]:
    ordered = sorted(reports, key=_report_key)
    selected_keys = {_report_key(report) for report in random.Random(seed).sample(ordered, count)}
    return [report for report in ordered if _report_key(report) in selected_keys]


def _selected_row(
    root: Path,
    report: Mapping[str, Any],
    *,
    index: int,
    preview_id: str,
    combination_label: str = "triple",
) -> dict[str, Any]:
    scenario_paths = [_resolve_path(root, Path(str(path))) for path in report.get("scenario_paths", [])]
    expected_rows = [
        {
            "scenario_id": row.get("scenario"),
            "scenario_path": _relative_path(root, _resolve_path(root, Path(str(row.get("scenario_path"))))),
            "expected_hypotheses": copy.deepcopy(row.get("expected_hypotheses", [])),
        }
        for row in report.get("expected_hypotheses", [])
        if isinstance(row, dict)
    ]
    expected_set = sorted(
        {
            str(hypothesis)
            for row in expected_rows
            for hypothesis in row.get("expected_hypotheses", [])
            if str(hypothesis)
        }
    )
    packages = [load_scenario_package(path) for path in scenario_paths]
    return {
        "index": index,
        "combination_id": f"{preview_id}-{combination_label}-{index:02d}",
        "scenario_ids": list(report.get("scenario_names", [])),
        "scenario_paths": [_relative_path(root, path) for path in scenario_paths],
        "domains": sorted({package.domain for package in packages}),
        "archetypes": list(report.get("archetypes", [])),
        "compatible": bool(report.get("compatible")),
        "decision": str(report.get("decision") or ""),
        "compatibility_reasons": list(report.get("reasons", [])),
        "expected_hypotheses": expected_rows,
        "expected_hypothesis_set": expected_set,
        "resource_claim_summary": copy.deepcopy(report.get("resource_claim_summary", {})),
        "target_state_conflict_count": int(report.get("target_state_conflict_count", 0)),
    }


def _coverage(packages: list[Any], selected_rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "pool_domains": sorted({package.domain for package in packages}),
        "pool_archetypes": sorted({str(package.spec.get("environment_archetype") or "") for package in packages}),
        "selected_domains": sorted({domain for row in selected_rows for domain in row.get("domains", [])}),
        "selected_archetypes": sorted({archetype for row in selected_rows for archetype in row.get("archetypes", [])}),
        "selected_scenario_ids": sorted({scenario for row in selected_rows for scenario in row.get("scenario_ids", [])}),
        "expected_hypotheses": sorted(
            {
                hypothesis
                for row in selected_rows
                for hypothesis in row.get("expected_hypothesis_set", [])
                if hypothesis
            }
        ),
    }


def _coverage_failures(preview: Mapping[str, Any], coverage: Mapping[str, Any]) -> list[str]:
    failures = []
    for domain in _string_list(preview.get("required_selected_domains", [])):
        if domain not in coverage.get("selected_domains", []):
            failures.append(f"required selected domain missing: {domain}")
    for archetype in _string_list(preview.get("required_selected_archetypes", [])):
        if archetype not in coverage.get("selected_archetypes", []):
            failures.append(f"required selected archetype missing: {archetype}")
    for hypothesis in _string_list(preview.get("required_expected_hypotheses", [])):
        if hypothesis not in coverage.get("expected_hypotheses", []):
            failures.append(f"required expected hypothesis missing: {hypothesis}")
    return failures


def _reason_counts(reports: list[Mapping[str, Any]]) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for report in reports:
        for reason in report.get("reason_details", []):
            if isinstance(reason, dict):
                counts[str(reason.get("code") or "unknown")] += 1
    return dict(sorted(counts.items()))


def _report_key(report: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(sorted(str(path) for path in report.get("scenario_paths", [])))


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
