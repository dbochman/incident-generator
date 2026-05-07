"""Release manifest generation for incident-generator artifacts."""

from __future__ import annotations

import hashlib
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .benchmark_result_helpers import (
    canonical_json as _canonical_json,
    sha256_file as _sha256_file,
    sha256_text as _sha256_text,
    write_json_file as _write_json_file,
)
from .judge_packs import DEFAULT_AGENT_ADAPTER_JUDGE_PACKS_RELATIVE, load_judge_pack_report
from .parsers import load_yaml
from .scenarios import build_catalog_report, list_scenario_packages, load_scenario_package
from .training_curriculum import build_training_curriculum


MANIFEST_API_VERSION = "incident-generator-release/v1alpha1"
SCENARIO_SCHEMA_VERSION = "sre-agent-scenario/v1alpha1"
BENCHMARK_RELEASE_SCHEMA_VERSION = "incident-generator.benchmark-release/v1"
BENCHMARK_SET_LISTING_SCHEMA_VERSION = "incident-generator.benchmark-set-listing/v1"
TRAINING_DRILL_EXPORT_SCHEMA_VERSION = "incident-generator.skill-drill-export/v1"
DEFAULT_BENCHMARK_SET_ALIASES_RELATIVE = Path("harness/alpha-benchmark-sets.yaml")
DEFAULT_GOLDEN_RESPONSE_SEEDS_RELATIVE = Path("harness/golden-response-seeds.yaml")
DEFAULT_INCORRECT_RESPONSE_SEEDS_RELATIVE = Path("harness/incorrect-response-seeds.yaml")
DEFAULT_SKILL_DRILL_OUTPUT_RELATIVE = Path("dist/training-drills")

BENCHMARK_SET_DEFINITIONS: tuple[dict[str, Any], ...] = (
    {
        "benchmark_set_id": "individual-live-20260505",
        "mode": "live real-mode",
        "collection_modes": ["real"],
        "item_kind": "scenario",
        "size": 41,
        "seed": None,
        "status": "complete",
        "host_profiles": ["linux-vm/local", "kind/local"],
        "source_paths": ["scenarios"],
    },
    {
        "benchmark_set_id": "linux-vm-pairs-safe-20260505",
        "mode": "live real-mode",
        "collection_modes": ["real"],
        "item_kind": "pair",
        "size": 23,
        "seed": None,
        "status": "complete",
        "host_profiles": ["linux-vm/local"],
        "source_paths": ["scenarios/linux"],
    },
    {
        "benchmark_set_id": "kind-curated-pairs-warm-20260506",
        "mode": "live real-mode plus replay",
        "collection_modes": ["real"],
        "item_kind": "pair",
        "size": 4,
        "seed": None,
        "status": "complete",
        "host_profiles": ["kind/warm-batch", "docker-over-ssh"],
        "source_paths": ["harness/benchmark-combo-llm-smoke.yaml"],
    },
    {
        "benchmark_set_id": "deterministic-replay-curated-warm-20260506",
        "mode": "deterministic replay result payload",
        "collection_modes": ["real"],
        "item_kind": "agent_replay",
        "size": 4,
        "seed": 20260506,
        "status": "complete",
        "host_profiles": [],
        "source_paths": ["harness/deterministic-replay-summary-example.json"],
    },
    {
        "benchmark_set_id": "benchmark-combo-llm-smoke-20260506",
        "mode": "fixture and live LLM smoke result payloads",
        "collection_modes": ["fixture", "real"],
        "item_kind": "pair",
        "size": 4,
        "seed": 20260506,
        "status": "complete",
        "host_profiles": [],
        "source_paths": [
            "harness/benchmark-combo-llm-smoke.yaml",
            "harness/benchmark-combo-llm-smoke-fixture-summary.json",
            "harness/benchmark-combo-llm-smoke-live-summary.json",
            "docs/benchmark-combo-llm-smoke.md",
            "docs/benchmark-combo-llm-smoke-live.md",
        ],
    },
    {
        "benchmark_set_id": "external-agent-adapter-smoke-20260506",
        "mode": "fixture-safe external adapter benchmark-set orchestration",
        "collection_modes": ["fixture", "real"],
        "item_kind": "adapter_exchange",
        "size": 2,
        "seed": 20260506,
        "status": "complete",
        "host_profiles": [],
        "source_paths": [
            "harness/agent-adapter-benchmark-set.yaml",
            "harness/agent-adapter-contract-example.json",
            "harness/agent-adapter-abstention-example.json",
        ],
    },
    {
        "benchmark_set_id": "kind-random8-warm-20260506",
        "mode": "live real-mode plus replay",
        "collection_modes": ["real"],
        "item_kind": "pair",
        "size": 8,
        "seed": 20260506,
        "status": "complete",
        "host_profiles": ["kind/warm-batch", "docker-over-ssh"],
        "source_paths": ["harness/random-pair-fixture-preview.yaml"],
        "notes": [
            "Retained live artifacts predate the warm-kind resource-claim audit; the source preview is the audited rerun definition."
        ],
    },
    {
        "benchmark_set_id": "kind-random16-warm-20260506",
        "mode": "live real-mode plus replay",
        "collection_modes": ["real"],
        "item_kind": "pair",
        "size": 16,
        "seed": 20260506,
        "status": "complete",
        "host_profiles": ["kind/warm-batch", "docker-over-ssh"],
        "source_paths": ["scenarios"],
    },
    {
        "benchmark_set_id": "triple-fixture-preview-20260506",
        "mode": "fixture preview",
        "collection_modes": ["fixture"],
        "item_kind": "triple",
        "size": 8,
        "seed": 20260506,
        "status": "complete",
        "host_profiles": [],
        "source_paths": ["harness/triple-benchmark-fixture-preview.yaml"],
    },
    {
        "benchmark_set_id": "noisy-checkout-vertical-fixture-20260506",
        "mode": "fixture render plus replay",
        "collection_modes": ["fixture"],
        "item_kind": "incident",
        "size": 5,
        "seed": 20260506,
        "status": "complete",
        "host_profiles": [],
        "source_paths": ["harness/noisy-checkout-vertical-smoke.yaml"],
    },
    {
        "benchmark_set_id": "noisy-partial-failure-fixture-20260506",
        "mode": "fixture render plus replay",
        "collection_modes": ["fixture"],
        "item_kind": "variant",
        "size": 4,
        "seed": 20260506,
        "status": "complete",
        "host_profiles": [],
        "source_paths": ["harness/noisy-partial-failure-pack.yaml"],
    },
    {
        "benchmark_set_id": "adversarial-fixture-inventory",
        "mode": "fixture inventory and smoke",
        "collection_modes": ["fixture"],
        "item_kind": "fixture",
        "size": 3,
        "seed": None,
        "status": "complete",
        "host_profiles": [],
        "source_paths": [
            "evals/pending-fixtures/kubernetes-pending-prompt-injection",
            "evals/linux-memory-fixtures/linux-memory-oom-prompt-injection",
            "evals/http-5xx-fixtures/http-5xx-prompt-injection",
        ],
    },
    {
        "benchmark_set_id": "adversarial-combo-fixture-20260506",
        "mode": "fixture render plus replay",
        "collection_modes": ["fixture"],
        "item_kind": "combo",
        "size": 3,
        "seed": 20260506,
        "status": "complete",
        "host_profiles": [],
        "source_paths": ["harness/adversarial-benchmark-combos.yaml"],
    },
    {
        "benchmark_set_id": "evidence-discipline-combo-fixture-20260506",
        "mode": "fixture render plus replay",
        "collection_modes": ["fixture"],
        "item_kind": "combo",
        "size": 3,
        "seed": 20260506,
        "status": "complete",
        "host_profiles": [],
        "source_paths": ["harness/missing-evidence-red-herring-combos.yaml"],
    },
    {
        "benchmark_set_id": "conflicting-signal-combo-fixture-20260506",
        "mode": "fixture render plus replay",
        "collection_modes": ["fixture"],
        "item_kind": "combo",
        "size": 3,
        "seed": 20260506,
        "status": "complete",
        "host_profiles": [],
        "source_paths": ["harness/conflicting-signal-combos.yaml"],
    },
    {
        "benchmark_set_id": "confidence-calibration-report-20260506",
        "mode": "deterministic baseline plus live LLM snapshot report",
        "collection_modes": ["fixture", "live"],
        "item_kind": "calibration_case",
        "size": 11,
        "seed": 20260506,
        "status": "complete_with_recorded_live_snapshot",
        "host_profiles": [],
        "source_paths": ["harness/confidence-calibration-report.yaml"],
    },
    {
        "benchmark_set_id": "cascading-temporal-fixture-20260506",
        "mode": "fixture model",
        "collection_modes": ["fixture"],
        "item_kind": "temporal_cascade",
        "size": 1,
        "seed": 20260506,
        "status": "complete",
        "host_profiles": [],
        "source_paths": ["harness/cascading-temporal-incident-model.yaml"],
    },
    {
        "benchmark_set_id": "recovery-after-diagnosis-fixture-20260506",
        "mode": "fixture recovery model",
        "collection_modes": ["fixture"],
        "item_kind": "recovery_case",
        "size": 2,
        "seed": 20260506,
        "status": "complete",
        "host_profiles": [],
        "source_paths": ["harness/recovery-after-diagnosis-benchmark.yaml"],
    },
)


def build_release_manifest(root: Path, *, artifact_dir: Path | None = None) -> dict[str, Any]:
    root = root.resolve()
    artifact_dir = artifact_dir or root / "dist"
    catalog = build_catalog_report(root)
    canonical_catalog = _canonical_json(catalog)
    package_metadata = _package_metadata(root / "pyproject.toml")
    return {
        "apiVersion": MANIFEST_API_VERSION,
        "kind": "ReleaseManifest",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "package": package_metadata,
        "git": {
            "sha": _git_output(root, ["git", "rev-parse", "HEAD"]),
            "dirty": bool(_git_output(root, ["git", "status", "--porcelain"])),
        },
        "scenario_catalog": {
            "count": catalog["count"],
            "hash_algorithm": "sha256",
            "hash": _sha256_text(canonical_catalog),
            "schema_version": SCENARIO_SCHEMA_VERSION,
        },
        "benchmark_release": _benchmark_release(root, catalog),
        "artifacts": _artifact_checksums(root, artifact_dir),
    }


def write_release_manifest(root: Path, output: Path, *, artifact_dir: Path | None = None) -> dict[str, Any]:
    manifest = build_release_manifest(root, artifact_dir=artifact_dir)
    _write_json_file(output, manifest)
    return manifest


def build_benchmark_set_listing(root: Path) -> dict[str, Any]:
    """Return benchmark set and alias metadata without touching live infrastructure."""

    root = root.resolve()
    benchmark_sets = _benchmark_sets(root)
    benchmark_set_aliases = _benchmark_set_aliases(root)
    return {
        "schema_version": BENCHMARK_SET_LISTING_SCHEMA_VERSION,
        "release": str(benchmark_set_aliases.get("release") or ""),
        "fixture_only_gate": True,
        "requires_docker": False,
        "benchmark_set_count": len(benchmark_sets),
        "alias_count": int(benchmark_set_aliases.get("alias_count") or 0),
        "benchmark_sets": benchmark_sets,
        "benchmark_set_aliases": benchmark_set_aliases,
        "validation_commands": [
            "python3 -m incident_generator validate --json",
            "python3 -m incident_generator catalog --json",
            "python3 -m incident_generator benchmark-sets --json",
        ],
    }


def _artifact_checksums(root: Path, artifact_dir: Path) -> list[dict[str, Any]]:
    if not artifact_dir.is_dir():
        return []
    artifacts: list[dict[str, Any]] = []
    for path in sorted(artifact_dir.iterdir()):
        if not path.is_file() or path.name == "release-manifest.json":
            continue
        if path.suffix not in {".whl", ".gz", ".zip"}:
            continue
        artifacts.append(
            {
                "path": _artifact_path(root, path),
                "size_bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    return artifacts


def _artifact_path(root: Path, path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(root))
    except ValueError:
        return str(resolved)


def _benchmark_release(root: Path, catalog: dict[str, Any]) -> dict[str, Any]:
    benchmark_set_aliases = _benchmark_set_aliases(root)
    training_seed_library = _training_seed_library(root, benchmark_set_aliases)
    incorrect_response_library = _incorrect_response_library(root, benchmark_set_aliases, training_seed_library)
    training_curriculum = build_training_curriculum(root)
    return {
        "schema_version": BENCHMARK_RELEASE_SCHEMA_VERSION,
        "hash_algorithm": "sha256",
        "scenario_hashes": _scenario_hashes(root, catalog),
        "benchmark_sets": _benchmark_sets(root),
        "benchmark_set_aliases": benchmark_set_aliases,
        "training_seed_library": training_seed_library,
        "incorrect_response_library": incorrect_response_library,
        "training_drill_export": _training_drill_export(root, training_seed_library, training_curriculum),
        "training_curriculum": training_curriculum,
        "judge_packs": _judge_packs(root),
        "supported_host_profiles": _supported_host_profiles(),
        "runtime_assumptions": _runtime_assumptions(),
        "known_limitations": _known_limitations(),
    }


def _scenario_hashes(root: Path, catalog: dict[str, Any]) -> list[dict[str, Any]]:
    package_paths = {str(path.relative_to(root)): path for path in list_scenario_packages(root)}
    rows: list[dict[str, Any]] = []
    for catalog_row in catalog.get("scenarios", []):
        relative = str(catalog_row.get("path") or "")
        package_path = package_paths.get(relative, root / relative)
        package = load_scenario_package(package_path)
        rows.append(
            {
                "name": str(catalog_row.get("name") or package.name),
                "path": relative,
                "domain": str(catalog_row.get("domain") or package.domain),
                "environment_archetype": str(catalog_row.get("environment_archetype") or ""),
                "live_readiness": str(catalog_row.get("live_readiness") or ""),
                "sha256": _sha256_tree(package.path),
            }
        )
    return rows


def _benchmark_sets(root: Path) -> list[dict[str, Any]]:
    sets: list[dict[str, Any]] = []
    for definition in BENCHMARK_SET_DEFINITIONS:
        entry = {key: value for key, value in definition.items() if key != "source_paths"}
        source_paths = list(definition.get("source_paths", []))
        entry["source_paths"] = source_paths
        entry["source_hashes"] = _source_hashes(root, source_paths)
        sets.append(entry)
    return sets


def _benchmark_set_aliases(root: Path) -> dict[str, Any]:
    manifest_path = root / DEFAULT_BENCHMARK_SET_ALIASES_RELATIVE
    manifest = load_yaml(manifest_path)
    aliases = manifest.get("aliases")
    if not isinstance(aliases, list):
        raise ValueError(f"{manifest_path} aliases must be a list")
    known_set_ids = {str(definition["benchmark_set_id"]) for definition in BENCHMARK_SET_DEFINITIONS}
    rows = [_benchmark_set_alias(root, alias, known_set_ids) for alias in aliases]
    return {
        "schema_version": str(manifest.get("schema_version") or ""),
        "release": str(manifest.get("release") or ""),
        "source_ref": {
            "path": str(DEFAULT_BENCHMARK_SET_ALIASES_RELATIVE),
            "kind": "file",
            "sha256": _sha256_file(manifest_path),
        },
        "alias_count": len(rows),
        "aliases": rows,
    }


def _benchmark_set_alias(root: Path, alias: Any, known_set_ids: set[str]) -> dict[str, Any]:
    if not isinstance(alias, dict):
        raise ValueError("benchmark set alias entries must be mappings")
    alias_id = _required_string(alias, "alias")
    set_ids = _required_string_list(alias, "benchmark_set_ids")
    missing_set_ids = sorted(set(set_ids) - known_set_ids)
    if missing_set_ids:
        raise ValueError(f"{alias_id} references unknown benchmark sets: {', '.join(missing_set_ids)}")
    source_manifests = _required_string_list(alias, "source_manifests")
    return {
        "alias": alias_id,
        "title": _required_string(alias, "title"),
        "benchmark_set_ids": set_ids,
        "item_count": _required_int(alias, "item_count"),
        "item_kind": _required_string(alias, "item_kind"),
        "collection_modes": _required_string_list(alias, "collection_modes"),
        "fixed_seeds": _required_int_list(alias, "fixed_seeds"),
        "supported_host_profiles": _required_string_list(alias, "supported_host_profiles", allow_empty=True),
        "source_manifests": source_manifests,
        "source_hashes": _source_hashes(root, source_manifests),
        "compatibility_guarantees": _required_string_list(alias, "compatibility_guarantees"),
    }


def _training_seed_library(root: Path, benchmark_set_aliases: dict[str, Any]) -> dict[str, Any]:
    manifest_path = root / DEFAULT_GOLDEN_RESPONSE_SEEDS_RELATIVE
    manifest = load_yaml(manifest_path)
    seeds = manifest.get("seeds")
    if not isinstance(seeds, list):
        raise ValueError(f"{manifest_path} seeds must be a list")
    known_aliases = {str(alias.get("alias") or "") for alias in benchmark_set_aliases.get("aliases", [])}
    known_set_ids = {str(definition["benchmark_set_id"]) for definition in BENCHMARK_SET_DEFINITIONS}
    rows = [_training_seed(root, seed, known_aliases, known_set_ids) for seed in seeds]
    return {
        "schema_version": str(manifest.get("schema_version") or ""),
        "release": str(manifest.get("release") or ""),
        "source_ref": {
            "path": str(DEFAULT_GOLDEN_RESPONSE_SEEDS_RELATIVE),
            "kind": "file",
            "sha256": _sha256_file(manifest_path),
        },
        "seed_count": len(rows),
        "aliases": sorted({row["release_alias"] for row in rows}),
        "entries": rows,
    }


def _training_seed(root: Path, seed: Any, known_aliases: set[str], known_set_ids: set[str]) -> dict[str, Any]:
    if not isinstance(seed, dict):
        raise ValueError("golden response seed entries must be mappings")
    seed_id = _required_string(seed, "id")
    release_alias = _required_string(seed, "release_alias")
    if release_alias not in known_aliases:
        raise ValueError(f"{seed_id} references unknown benchmark alias: {release_alias}")
    benchmark_set_id = _required_string(seed, "benchmark_set_id")
    if benchmark_set_id not in known_set_ids:
        raise ValueError(f"{seed_id} references unknown benchmark set: {benchmark_set_id}")
    source_manifests = _required_string_list(seed, "source_manifests")
    source_hashes = _source_hashes(root, source_manifests)
    missing_sources = [row["path"] for row in source_hashes if row["kind"] == "missing"]
    if missing_sources:
        raise ValueError(f"{seed_id} references missing source manifests: {', '.join(missing_sources)}")
    response_markdown = _required_string(seed, "supervised_response")
    return {
        "id": seed_id,
        "title": _required_string(seed, "title"),
        "release_alias": release_alias,
        "benchmark_set_id": benchmark_set_id,
        "drill_type": _required_string(seed, "drill_type"),
        "scenario_ids": _required_string_list(seed, "scenario_ids"),
        "source_manifests": source_manifests,
        "source_hashes": source_hashes,
        "release_manifest_paths": _required_string_list(seed, "release_manifest_paths"),
        "learner_visible_evidence_refs": _training_seed_evidence_refs(seed),
        "expected_hypotheses": _training_seed_hypotheses(seed),
        "redaction_checks": _required_string_list(seed, "redaction_checks"),
        "validation_commands": _required_string_list(seed, "validation_commands"),
        "response_markdown_sha256": _sha256_text(response_markdown),
    }


def _training_seed_evidence_refs(seed: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in _required_mapping_list(seed, "learner_visible_evidence"):
        rows.append(
            {
                "id": _required_string(item, "id"),
                "ref": _required_string(item, "ref"),
                "observation_sha256": _sha256_text(_required_string(item, "observation")),
            }
        )
    return rows


def _training_seed_hypotheses(seed: dict[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for item in _required_mapping_list(seed, "expected_hypotheses"):
        rows.append(
            {
                "id": _required_string(item, "id"),
                "confidence": _required_string(item, "confidence"),
            }
        )
    return rows


def _incorrect_response_library(
    root: Path,
    benchmark_set_aliases: dict[str, Any],
    training_seed_library: dict[str, Any],
) -> dict[str, Any]:
    manifest_path = root / DEFAULT_INCORRECT_RESPONSE_SEEDS_RELATIVE
    manifest = load_yaml(manifest_path)
    examples = manifest.get("examples")
    if not isinstance(examples, list):
        raise ValueError(f"{manifest_path} examples must be a list")
    known_aliases = {str(alias.get("alias") or "") for alias in benchmark_set_aliases.get("aliases", [])}
    known_set_ids = {str(definition["benchmark_set_id"]) for definition in BENCHMARK_SET_DEFINITIONS}
    golden_seed_rows = {
        str(seed.get("id") or ""): seed
        for seed in training_seed_library.get("entries", [])
        if isinstance(seed, dict)
    }
    rows = [_incorrect_response_example(root, example, known_aliases, known_set_ids, golden_seed_rows) for example in examples]
    return {
        "schema_version": str(manifest.get("schema_version") or ""),
        "release": str(manifest.get("release") or ""),
        "source_ref": {
            "path": str(DEFAULT_INCORRECT_RESPONSE_SEEDS_RELATIVE),
            "kind": "file",
            "sha256": _sha256_file(manifest_path),
        },
        "example_count": len(rows),
        "failure_modes": sorted({row["failure_mode"] for row in rows}),
        "entries": rows,
    }


def _incorrect_response_example(
    root: Path,
    example: Any,
    known_aliases: set[str],
    known_set_ids: set[str],
    golden_seed_rows: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if not isinstance(example, dict):
        raise ValueError("incorrect response seed entries must be mappings")
    example_id = _required_string(example, "id")
    release_alias = _required_string(example, "release_alias")
    if release_alias not in known_aliases:
        raise ValueError(f"{example_id} references unknown benchmark alias: {release_alias}")
    benchmark_set_id = _required_string(example, "benchmark_set_id")
    if benchmark_set_id not in known_set_ids:
        raise ValueError(f"{example_id} references unknown benchmark set: {benchmark_set_id}")
    golden_seed_id = _required_string(example, "golden_seed_id")
    golden_seed = golden_seed_rows.get(golden_seed_id)
    if golden_seed is None:
        raise ValueError(f"{example_id} references unknown golden response seed: {golden_seed_id}")
    scenario_ids = _required_string_list(example, "scenario_ids")
    if release_alias != str(golden_seed.get("release_alias") or ""):
        raise ValueError(f"{example_id} release alias does not match golden response seed: {golden_seed_id}")
    if benchmark_set_id != str(golden_seed.get("benchmark_set_id") or ""):
        raise ValueError(f"{example_id} benchmark set does not match golden response seed: {golden_seed_id}")
    if scenario_ids != list(golden_seed.get("scenario_ids") or []):
        raise ValueError(f"{example_id} scenarios do not match golden response seed: {golden_seed_id}")
    source_manifests = _required_string_list(example, "source_manifests")
    source_hashes = _source_hashes(root, source_manifests)
    missing_sources = [row["path"] for row in source_hashes if row["kind"] == "missing"]
    if missing_sources:
        raise ValueError(f"{example_id} references missing source manifests: {', '.join(missing_sources)}")
    incorrect_response = _required_string(example, "incorrect_response")
    expected_correction = _required_string(example, "expected_correction")
    return {
        "id": example_id,
        "title": _required_string(example, "title"),
        "golden_seed_id": golden_seed_id,
        "release_alias": release_alias,
        "benchmark_set_id": benchmark_set_id,
        "drill_type": _required_string(example, "drill_type"),
        "failure_mode": _required_string(example, "failure_mode"),
        "scenario_ids": scenario_ids,
        "source_manifests": source_manifests,
        "source_hashes": source_hashes,
        "release_manifest_paths": _required_string_list(example, "release_manifest_paths"),
        "learner_visible_evidence_refs": _required_string_list(example, "learner_visible_evidence_refs"),
        "expected_hypotheses": _required_string_list(example, "expected_hypotheses"),
        "forbidden_hypotheses": _optional_string_list(example, "forbidden_hypotheses"),
        "expected_failure_checks": _required_string_list(example, "expected_failure_checks"),
        "redaction_checks": _required_string_list(example, "redaction_checks"),
        "validation_commands": _required_string_list(example, "validation_commands"),
        "incorrect_response_markdown_sha256": _sha256_text(incorrect_response),
        "expected_correction_markdown_sha256": _sha256_text(expected_correction),
    }


def _training_drill_export(
    root: Path,
    training_seed_library: dict[str, Any],
    training_curriculum: dict[str, Any],
) -> dict[str, Any]:
    incorrect_path = root / DEFAULT_INCORRECT_RESPONSE_SEEDS_RELATIVE
    incorrect_manifest = load_yaml(incorrect_path)
    examples = incorrect_manifest.get("examples")
    if not isinstance(examples, list):
        raise ValueError(f"{incorrect_path} examples must be a list")
    return {
        "schema_version": TRAINING_DRILL_EXPORT_SCHEMA_VERSION,
        "release": str(training_seed_library.get("release") or ""),
        "command": (
            "python3 -m incident_generator skill-drill-export "
            f"--output-dir {DEFAULT_SKILL_DRILL_OUTPUT_RELATIVE.as_posix()}"
        ),
        "bundle_count": int(training_seed_library.get("seed_count") or 0),
        "incorrect_response_count": len(examples),
        "source_refs": [
            {
                "path": str(DEFAULT_GOLDEN_RESPONSE_SEEDS_RELATIVE),
                "kind": "file",
                "sha256": _sha256_file(root / DEFAULT_GOLDEN_RESPONSE_SEEDS_RELATIVE),
            },
            {
                "path": str(DEFAULT_INCORRECT_RESPONSE_SEEDS_RELATIVE),
                "kind": "file",
                "sha256": _sha256_file(incorrect_path),
            },
            training_curriculum["source_refs"][0],
        ],
        "curriculum": {
            "path": "curriculum.json",
            "schema_version": str(training_curriculum.get("schema_version") or ""),
            "source_manifest": str(training_curriculum["source_refs"][0]["path"]),
            "difficulty_order": list(training_curriculum.get("difficulty_order") or []),
            "entry_count": int(training_curriculum.get("entry_count") or 0),
            "domain_count": int(training_curriculum.get("domain_count") or 0),
            "sha256": str(training_curriculum["source_refs"][0]["sha256"]),
        },
        "bundle_files": [
            "provenance.json",
            "drill.md",
            "expected-evidence.yaml",
            "supervised-response.md",
            "incorrect-responses.yaml",
        ],
        "validation_commands": [
            "python3 -m unittest tests.test_incident_generator_skill_drill_export",
            (
                "PYTHONPATH=packages/incident-generator python3 -m incident_generator --root . "
                "skill-drill-export --output-dir /tmp/incident-generator-skill-drills "
                "--created-at 2026-05-06T00:00:00Z --json"
            ),
            "python3 -m unittest tests.test_incident_generator_export",
            "make docs-check",
        ],
    }


def _source_hashes(root: Path, relative_paths: list[str]) -> list[dict[str, Any]]:
    hashes: list[dict[str, Any]] = []
    for relative in relative_paths:
        path = root / relative
        if path.is_file():
            hashes.append({"path": relative, "kind": "file", "sha256": _sha256_file(path)})
        elif path.is_dir():
            hashes.append({"path": relative, "kind": "directory", "sha256": _sha256_tree(path)})
        else:
            hashes.append({"path": relative, "kind": "missing", "sha256": ""})
    return hashes


def _required_string(mapping: dict[str, Any], field: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value:
        raise ValueError(f"benchmark set alias missing required string field: {field}")
    return value


def _required_int(mapping: dict[str, Any], field: str) -> int:
    value = mapping.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"benchmark set alias missing required integer field: {field}")
    return value


def _required_string_list(mapping: dict[str, Any], field: str, *, allow_empty: bool = False) -> list[str]:
    value = mapping.get(field)
    if not isinstance(value, list):
        raise ValueError(f"benchmark set alias missing required list field: {field}")
    items = [item for item in value if isinstance(item, str) and item]
    if len(items) != len(value):
        raise ValueError(f"benchmark set alias list must contain only non-empty strings: {field}")
    if not allow_empty and not items:
        raise ValueError(f"benchmark set alias list must not be empty: {field}")
    return items


def _optional_string_list(mapping: dict[str, Any], field: str) -> list[str]:
    value = mapping.get(field, [])
    if not isinstance(value, list):
        raise ValueError(f"benchmark set alias optional list field must be a list: {field}")
    items = [item for item in value if isinstance(item, str) and item]
    if len(items) != len(value):
        raise ValueError(f"benchmark set alias optional list must contain only non-empty strings: {field}")
    return items


def _required_mapping_list(mapping: dict[str, Any], field: str) -> list[dict[str, Any]]:
    value = mapping.get(field)
    if not isinstance(value, list):
        raise ValueError(f"benchmark set alias missing required list field: {field}")
    items = [item for item in value if isinstance(item, dict)]
    if len(items) != len(value) or not items:
        raise ValueError(f"benchmark set alias list must contain only mappings: {field}")
    return items


def _required_int_list(mapping: dict[str, Any], field: str) -> list[int]:
    value = mapping.get(field)
    if not isinstance(value, list):
        raise ValueError(f"benchmark set alias missing required list field: {field}")
    items = [item for item in value if isinstance(item, int) and not isinstance(item, bool)]
    if len(items) != len(value):
        raise ValueError(f"benchmark set alias list must contain only integers: {field}")
    return items


def _judge_packs(root: Path) -> dict[str, Any]:
    report = load_judge_pack_report(root, judge_packs_path=DEFAULT_AGENT_ADAPTER_JUDGE_PACKS_RELATIVE)
    return {
        "source_ref": report["source_ref"],
        "pack_count": report["pack_count"],
        "packs": report["packs"],
    }


def _supported_host_profiles() -> list[dict[str, Any]]:
    return [
        {
            "profile_id": "linux-vm/local",
            "intended_use": "Individual Linux scenarios and Linux pair sweeps.",
            "floor": {"cpu_cores": 2, "memory_gib": 2, "docker_disk_gib": 5},
            "recommended": {"cpu_cores": 4, "memory_gib": 4, "docker_disk_gib": 10},
        },
        {
            "profile_id": "kind/local",
            "intended_use": "Individual kind scenarios and small curated pairs.",
            "floor": {"cpu_cores": 4, "memory_gib": 8, "docker_disk_gib": 15},
            "recommended": {"cpu_cores": 6, "memory_gib": 12, "docker_disk_gib": 20},
        },
        {
            "profile_id": "kind/warm-batch",
            "intended_use": "Warm kind random chunks with observability reused across runs.",
            "floor": {"cpu_cores": 6, "memory_gib": 12, "docker_disk_gib": 20},
            "recommended": {"cpu_cores": 8, "memory_gib": 16, "docker_disk_gib": 30},
        },
        {
            "profile_id": "docker-over-ssh",
            "intended_use": "Remote Docker daemon for either supported archetype.",
            "floor": {"selected_archetype": "same as linux-vm/local or kind/local", "ssh": "reliable"},
            "recommended": {
                "selected_archetype": "same as selected archetype",
                "remote_docker_command_headroom_seconds": 90,
            },
        },
    ]


def _runtime_assumptions() -> dict[str, Any]:
    return {
        "python_requires": ">=3.10",
        "fixture_mode_requires_docker": False,
        "real_mode_required_tools": ["docker", "docker compose v2", "kind", "kubectl", "helm", "curl"],
        "docker_hosts": {
            "supported": ["local Docker daemon", "DOCKER_HOST=ssh://<benchmark-host>"],
            "production_daemon_supported": False,
            "serial_real_batches": True,
        },
        "kind": {
            "config_api_version": "kind.x-k8s.io/v1alpha4",
            "default_cluster_name": "sre-agent-phase-a",
            "control_plane_nodes": 1,
            "worker_nodes": 2,
            "host_ports": [8080, 8443],
            "node_image": "kind CLI default unless the operator pins a node image and records it in artifacts",
        },
        "linux_vm": {
            "compose_services": ["linux-target", "prometheus", "loki", "tempo", "fake-pagerduty"],
            "host_ports": [9090, 3100, 3200, 8081],
            "target_container_mem_limit": "512m",
            "fault_tmpfs": {"size": "256m", "nr_inodes": 4096},
            "prometheus_retention": "2h",
        },
        "observability": {
            "prometheus": {"request_cpu": "100m", "request_memory": "512Mi", "limit_memory": "1Gi"},
            "tempo": {"request_cpu": "100m", "request_memory": "256Mi", "limit_memory": "512Mi"},
            "loki_persistence": "disabled",
            "grafana": "disabled",
            "retention": "2h",
        },
        "small_addon_limits": {
            "misbehaving_app": {"request_cpu": "50m", "request_memory": "64Mi", "limit_memory": "128Mi"},
            "ecommerce_http_service": {"request_cpu": "25m", "request_memory": "48Mi"},
            "ecommerce_http_load_generator": {
                "request_cpu": "50m",
                "request_memory": "96Mi",
                "limit_memory": "192Mi",
            },
            "postgres": {"request_cpu": "100m", "request_memory": "128Mi", "limit_memory": "256Mi"},
            "tls_target": {"request_cpu": "25m", "request_memory": "32Mi", "limit_memory": "96Mi"},
            "dns_probe": {"request_cpu": "10m", "request_memory": "32Mi", "limit_memory": "128Mi"},
        },
        "timeout_defaults": {
            "SRE_AGENT_KIND_WAIT": "120s",
            "SRE_AGENT_KIND_API_WAIT_SECONDS": 120,
            "SRE_AGENT_KIND_CREATE_TIMEOUT_SECONDS": 300,
            "SRE_AGENT_REMOTE_DOCKER_TIMEOUT_SECONDS": 60,
            "SRE_AGENT_OBSERVABILITY_TIMEOUT": "10m",
            "SRE_AGENT_HELM_TIMEOUT": "5m",
            "SRE_AGENT_MISBEHAVING_APP_HELM_TIMEOUT": "3m",
            "SRE_AGENT_TLS_TARGET_HELM_TIMEOUT": "3m",
            "SRE_AGENT_DNS_TLS_PROBE_TIMEOUT": "120s",
            "SRE_AGENT_COREDNS_ROLLOUT_TIMEOUT": "120s",
            "SRE_AGENT_SCENARIO_WAIT_TIMEOUT": "120s",
        },
    }


def _known_limitations() -> list[str]:
    return [
        "eks-staging dispatch is intentionally blocked and is not part of this benchmark release.",
        "Representative real-mode live matrix execution is operator-run and is not automated in CI.",
        "Real-mode combinations must share one environment_archetype and avoid conflicting resource_claims.",
        "Cross-archetype combinations are fixture-only until multi-harness orchestration is designed.",
        "The benchmark runner selected-set path is fixture-safe and local-subprocess only; Tier 2 and mixed judge packs fail closed until live judge execution is implemented.",
        "Fresh live LLM benchmark execution requires model credentials and separate-family judge settings.",
        "Host capacity ceilings are support profiles, not measured hard requirements; retained artifacts should record host fingerprints.",
        "Random warm-kind live artifacts from 2026-05-06 predate the current audited resource-claim sampler.",
    ]


def _package_metadata(path: Path) -> dict[str, str]:
    metadata = {"name": "", "version": "", "requires_python": ""}
    if not path.is_file():
        return metadata
    in_project = False
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped == "[project]":
            in_project = True
            continue
        if stripped.startswith("[") and stripped.endswith("]"):
            in_project = False
        if not in_project or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip().replace("-", "_")
        if key in metadata:
            metadata[key] = value.strip().strip('"')
    return metadata


def _git_output(root: Path, args: list[str]) -> str:
    completed = subprocess.run(args, cwd=root, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _sha256_tree(path: Path) -> str:
    digest = hashlib.sha256()
    for child in sorted(candidate for candidate in path.rglob("*") if candidate.is_file()):
        relative = child.relative_to(path).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with child.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()
