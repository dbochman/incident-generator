"""Portable training drill bundle export for benchmark-derived seeds."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import yaml

from .benchmark_result_helpers import (
    display_path as _display_path,
    resolve_path as _resolve_path,
    sha256_file as _sha256_file,
    sha256_text as _sha256_text,
    source_ref as _source_ref,
    utc_now as _utc_now,
    write_json_file as _write_json_file,
)
from .parsers import load_yaml, redact
from .training_curriculum import (
    DEFAULT_TRAINING_CURRICULUM_RELATIVE,
    TrainingCurriculumError,
    build_training_curriculum,
)


SKILL_DRILL_EXPORT_SCHEMA_VERSION = "incident-generator.skill-drill-export/v1"
SKILL_DRILL_PROVENANCE_SCHEMA_VERSION = "incident-generator.skill-drill-provenance/v1"
EXPECTED_EVIDENCE_SCHEMA_VERSION = "incident-generator.skill-drill-expected-evidence/v1"
INCORRECT_RESPONSES_SCHEMA_VERSION = "incident-generator.skill-drill-incorrect-responses/v1"
DEFAULT_SKILL_DRILL_OUTPUT_RELATIVE = Path("dist/training-drills")
DEFAULT_GOLDEN_RESPONSE_SEEDS_RELATIVE = Path("harness/golden-response-seeds.yaml")
DEFAULT_INCORRECT_RESPONSE_SEEDS_RELATIVE = Path("harness/incorrect-response-seeds.yaml")

_BUNDLE_FILENAMES = (
    "provenance.json",
    "drill.md",
    "expected-evidence.yaml",
    "supervised-response.md",
    "incorrect-responses.yaml",
)


class SkillDrillExportError(ValueError):
    """Raised when reviewed training seed manifests cannot be exported."""


def export_skill_drill_bundles(
    root: Path,
    *,
    output_dir: Path = DEFAULT_SKILL_DRILL_OUTPUT_RELATIVE,
    golden_seeds_path: Path = DEFAULT_GOLDEN_RESPONSE_SEEDS_RELATIVE,
    incorrect_seeds_path: Path = DEFAULT_INCORRECT_RESPONSE_SEEDS_RELATIVE,
    curriculum_path: Path = DEFAULT_TRAINING_CURRICULUM_RELATIVE,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Write portable skill drill bundles and return the export manifest."""

    root = root.resolve()
    output_dir = _resolve_path(root, output_dir)
    golden_path = _resolve_path(root, golden_seeds_path)
    incorrect_path = _resolve_path(root, incorrect_seeds_path)
    curriculum_source_path = _resolve_path(root, curriculum_path)
    created = created_at or _utc_now()

    golden_manifest = load_yaml(golden_path)
    incorrect_manifest = load_yaml(incorrect_path)
    try:
        curriculum = build_training_curriculum(
            root,
            curriculum_path=curriculum_source_path,
            golden_seeds_path=golden_path,
            incorrect_seeds_path=incorrect_path,
        )
    except TrainingCurriculumError as exc:
        raise SkillDrillExportError(f"training curriculum invalid: {exc}") from exc
    release = _required_string(golden_manifest, "release")
    if _required_string(incorrect_manifest, "release") != release:
        raise SkillDrillExportError("golden and incorrect response seed manifests must use the same release")
    if curriculum["release"] != release:
        raise SkillDrillExportError("training curriculum release must match seed manifests")

    seeds = _required_mapping_list(golden_manifest, "seeds")
    seed_by_id = {_required_string(seed, "id"): seed for seed in seeds}
    incorrect_examples = _required_mapping_list(incorrect_manifest, "examples")
    negatives_by_golden: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for example in incorrect_examples:
        golden_seed_id = _required_string(example, "golden_seed_id")
        golden_seed = seed_by_id.get(golden_seed_id)
        if golden_seed is None:
            raise SkillDrillExportError(f"{_required_string(example, 'id')} references unknown golden seed: {golden_seed_id}")
        _validate_incorrect_example(root, example, golden_seed)
        negatives_by_golden[golden_seed_id].append(example)

    output_dir.mkdir(parents=True, exist_ok=True)
    bundles: list[dict[str, Any]] = []
    for seed in seeds:
        bundles.append(
            _write_bundle(
                root,
                output_dir,
                seed=seed,
                incorrect_examples=negatives_by_golden.get(_required_string(seed, "id"), []),
                release=release,
                created_at=created,
            )
        )

    curriculum_export = _curriculum_export_payload(curriculum, bundles)
    curriculum_export_path = output_dir / "curriculum.json"
    _write_json_file(curriculum_export_path, curriculum_export)

    manifest = {
        "schema_version": SKILL_DRILL_EXPORT_SCHEMA_VERSION,
        "release": release,
        "created_at": created,
        "bundle_root": ".",
        "source_refs": [
            _source_ref(golden_path, _display_path(root, golden_path)),
            _source_ref(incorrect_path, _display_path(root, incorrect_path)),
            _source_ref(curriculum_source_path, _display_path(root, curriculum_source_path)),
        ],
        "bundle_count": len(bundles),
        "incorrect_response_count": sum(bundle["incorrect_response_count"] for bundle in bundles),
        "bundle_files": list(_BUNDLE_FILENAMES),
        "curriculum": {
            "path": "curriculum.json",
            "schema_version": curriculum_export["schema_version"],
            "difficulty_order": curriculum_export["difficulty_order"],
            "entry_count": curriculum_export["entry_count"],
            "domain_count": curriculum_export["domain_count"],
            "sha256": _sha256_file(curriculum_export_path),
        },
        "bundles": bundles,
    }
    manifest_path = output_dir / "manifest.json"
    _write_json_file(manifest_path, manifest)
    return {**manifest, "manifest_path": _display_path(root, manifest_path)}


def _curriculum_export_payload(curriculum: dict[str, Any], bundles: list[dict[str, Any]]) -> dict[str, Any]:
    bundle_by_seed = {bundle["bundle_id"]: bundle for bundle in bundles}
    entries: list[dict[str, Any]] = []
    for entry in curriculum["entries"]:
        seed_id = entry["golden_seed_id"]
        bundle = bundle_by_seed.get(seed_id)
        if bundle is None:
            raise SkillDrillExportError(f"training curriculum references unexported seed: {seed_id}")
        entries.append(
            {
                "order": entry["order"],
                "difficulty": entry["difficulty"],
                "domain": entry["domain"],
                "golden_seed_id": seed_id,
                "title": entry["title"],
                "benchmark_set_id": entry["benchmark_set_id"],
                "drill_type": entry["drill_type"],
                "scenario_ids": entry["scenario_ids"],
                "learning_objective": entry["learning_objective"],
                "prerequisite_seed_ids": entry["prerequisite_seed_ids"],
                "paired_negative_ids": entry["paired_negative_ids"],
                "bundle_path": bundle["bundle_path"],
                "incorrect_response_count": bundle["incorrect_response_count"],
            }
        )
    return {
        "schema_version": curriculum["schema_version"],
        "release": curriculum["release"],
        "difficulty_order": curriculum["difficulty_order"],
        "level_count": curriculum["level_count"],
        "domain_count": curriculum["domain_count"],
        "entry_count": curriculum["entry_count"],
        "levels": curriculum["levels"],
        "entries": entries,
    }


def _write_bundle(
    root: Path,
    output_dir: Path,
    *,
    seed: dict[str, Any],
    incorrect_examples: list[dict[str, Any]],
    release: str,
    created_at: str,
) -> dict[str, Any]:
    seed_id = _required_string(seed, "id")
    benchmark_set_id = _required_string(seed, "benchmark_set_id")
    bundle_relative = Path(_safe_segment(benchmark_set_id)) / _safe_segment(seed_id)
    bundle_dir = output_dir / bundle_relative
    bundle_dir.mkdir(parents=True, exist_ok=True)

    files = {
        "provenance.json": json.dumps(
            _provenance_payload(root, seed, incorrect_examples, release=release, created_at=created_at),
            indent=2,
            sort_keys=True,
        )
        + "\n",
        "drill.md": _render_drill_markdown(seed, release=release),
        "expected-evidence.yaml": _dump_yaml(_expected_evidence_payload(seed, release=release)),
        "supervised-response.md": _required_string(seed, "supervised_response").rstrip() + "\n",
        "incorrect-responses.yaml": _dump_yaml(
            _incorrect_responses_payload(seed, incorrect_examples, release=release)
        ),
    }
    for filename, content in files.items():
        (bundle_dir / filename).write_text(content, encoding="utf-8")

    file_hashes = {
        filename: {
            "path": str(bundle_relative / filename),
            "sha256": _sha256_file(bundle_dir / filename),
        }
        for filename in _BUNDLE_FILENAMES
    }
    return {
        "bundle_id": seed_id,
        "case_id": seed_id,
        "title": _required_string(seed, "title"),
        "release_alias": _required_string(seed, "release_alias"),
        "benchmark_set_id": benchmark_set_id,
        "drill_type": _required_string(seed, "drill_type"),
        "scenario_ids": _required_string_list(seed, "scenario_ids"),
        "bundle_path": str(bundle_relative),
        "incorrect_response_count": len(incorrect_examples),
        "files": file_hashes,
    }


def _render_drill_markdown(seed: dict[str, Any], *, release: str) -> str:
    evidence = _required_mapping_list(seed, "learner_visible_evidence")
    scenario_ids = _required_string_list(seed, "scenario_ids")
    lines = [
        f"# {_required_string(seed, 'title')}",
        "",
        f"Release: `{release}`",
        f"Drill type: `{_required_string(seed, 'drill_type')}`",
        f"Benchmark set: `{_required_string(seed, 'benchmark_set_id')}`",
        "",
        "Use only the evidence below to write an incident-response note with diagnosis, confidence, uncertainty, next checks, and action boundary.",
        "",
        "## Scenario IDs",
        "",
    ]
    lines.extend(f"- `{scenario_id}`" for scenario_id in scenario_ids)
    lines.extend(["", "## Evidence", ""])
    for item in evidence:
        lines.extend(
            [
                f"### `{_required_string(item, 'id')}`",
                "",
                f"Ref: `{_required_string(item, 'ref')}`",
                "",
                redact(_required_string(item, "observation")),
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _expected_evidence_payload(seed: dict[str, Any], *, release: str) -> dict[str, Any]:
    return {
        "schema_version": EXPECTED_EVIDENCE_SCHEMA_VERSION,
        "release": release,
        "golden_seed_id": _required_string(seed, "id"),
        "title": _required_string(seed, "title"),
        "release_alias": _required_string(seed, "release_alias"),
        "benchmark_set_id": _required_string(seed, "benchmark_set_id"),
        "drill_type": _required_string(seed, "drill_type"),
        "scenario_ids": _required_string_list(seed, "scenario_ids"),
        "learner_visible_evidence": [
            {
                "id": _required_string(item, "id"),
                "ref": _required_string(item, "ref"),
                "observation": redact(_required_string(item, "observation")),
                "observation_sha256": _sha256_text(redact(_required_string(item, "observation"))),
            }
            for item in _required_mapping_list(seed, "learner_visible_evidence")
        ],
        "expected_hypotheses": [
            {
                "id": _required_string(item, "id"),
                "confidence": _required_string(item, "confidence"),
                "rationale": _required_string(item, "rationale"),
            }
            for item in _required_mapping_list(seed, "expected_hypotheses")
        ],
        "redaction_checks": _required_string_list(seed, "redaction_checks"),
        "validation_commands": _required_string_list(seed, "validation_commands"),
    }


def _incorrect_responses_payload(
    seed: dict[str, Any],
    incorrect_examples: list[dict[str, Any]],
    *,
    release: str,
) -> dict[str, Any]:
    seed_id = _required_string(seed, "id")
    return {
        "schema_version": INCORRECT_RESPONSES_SCHEMA_VERSION,
        "release": release,
        "golden_seed_id": seed_id,
        "example_count": len(incorrect_examples),
        "examples": [
            {
                "id": _required_string(example, "id"),
                "title": _required_string(example, "title"),
                "failure_mode": _required_string(example, "failure_mode"),
                "drill_type": _required_string(example, "drill_type"),
                "scenario_ids": _required_string_list(example, "scenario_ids"),
                "learner_visible_evidence_refs": _required_string_list(example, "learner_visible_evidence_refs"),
                "expected_hypotheses": _required_string_list(example, "expected_hypotheses"),
                "forbidden_hypotheses": _optional_string_list(example, "forbidden_hypotheses"),
                "incorrect_response": redact(_required_string(example, "incorrect_response")),
                "expected_failure_checks": _required_string_list(example, "expected_failure_checks"),
                "expected_correction": redact(_required_string(example, "expected_correction")),
                "redaction_checks": _required_string_list(example, "redaction_checks"),
            }
            for example in incorrect_examples
        ],
    }


def _provenance_payload(
    root: Path,
    seed: dict[str, Any],
    incorrect_examples: list[dict[str, Any]],
    *,
    release: str,
    created_at: str,
) -> dict[str, Any]:
    source_manifests = _required_string_list(seed, "source_manifests")
    source_hashes = _checked_source_hashes(root, source_manifests, label=_required_string(seed, "id"))
    response = _required_string(seed, "supervised_response")
    evidence = _required_mapping_list(seed, "learner_visible_evidence")
    return {
        "schema_version": SKILL_DRILL_PROVENANCE_SCHEMA_VERSION,
        "release": release,
        "created_at": created_at,
        "golden_seed_id": _required_string(seed, "id"),
        "title": _required_string(seed, "title"),
        "release_alias": _required_string(seed, "release_alias"),
        "benchmark_set_id": _required_string(seed, "benchmark_set_id"),
        "drill_type": _required_string(seed, "drill_type"),
        "scenario_ids": _required_string_list(seed, "scenario_ids"),
        "source_manifests": source_manifests,
        "source_hashes": source_hashes,
        "release_manifest_paths": _required_string_list(seed, "release_manifest_paths"),
        "learner_visible_evidence_refs": [
            {
                "id": _required_string(item, "id"),
                "ref": _required_string(item, "ref"),
                "observation_sha256": _sha256_text(redact(_required_string(item, "observation"))),
            }
            for item in evidence
        ],
        "supervised_response_sha256": _sha256_text(response),
        "incorrect_response_ids": [_required_string(example, "id") for example in incorrect_examples],
        "redaction_checks": _required_string_list(seed, "redaction_checks"),
    }


def _validate_incorrect_example(root: Path, example: dict[str, Any], seed: dict[str, Any]) -> None:
    example_id = _required_string(example, "id")
    golden_seed_id = _required_string(seed, "id")
    if _required_string(example, "release_alias") != _required_string(seed, "release_alias"):
        raise SkillDrillExportError(f"{example_id} release alias does not match golden seed: {golden_seed_id}")
    if _required_string(example, "benchmark_set_id") != _required_string(seed, "benchmark_set_id"):
        raise SkillDrillExportError(f"{example_id} benchmark set does not match golden seed: {golden_seed_id}")
    if _required_string_list(example, "scenario_ids") != _required_string_list(seed, "scenario_ids"):
        raise SkillDrillExportError(f"{example_id} scenarios do not match golden seed: {golden_seed_id}")
    _checked_source_hashes(
        root,
        _required_string_list(example, "source_manifests"),
        label=example_id,
    )


def _dump_yaml(payload: dict[str, Any]) -> str:
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=False).rstrip() + "\n"


def _source_hashes(root: Path, relative_paths: list[str]) -> list[dict[str, Any]]:
    return [_source_ref(root / relative, relative) for relative in relative_paths]


def _checked_source_hashes(root: Path, relative_paths: list[str], *, label: str) -> list[dict[str, Any]]:
    source_hashes = _source_hashes(root, relative_paths)
    missing = [row["path"] for row in source_hashes if row["kind"] == "missing"]
    if missing:
        raise SkillDrillExportError(f"{label} references missing source manifests: {', '.join(missing)}")
    return source_hashes


def _safe_segment(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    if not safe:
        raise SkillDrillExportError("bundle path segment cannot be empty")
    return safe


def _required_string(mapping: dict[str, Any], field: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value:
        raise SkillDrillExportError(f"skill drill export missing required string field: {field}")
    return value


def _required_string_list(mapping: dict[str, Any], field: str, *, allow_empty: bool = False) -> list[str]:
    value = mapping.get(field)
    if not isinstance(value, list):
        raise SkillDrillExportError(f"skill drill export missing required list field: {field}")
    items = [item for item in value if isinstance(item, str) and item]
    if len(items) != len(value):
        raise SkillDrillExportError(f"skill drill export list must contain only non-empty strings: {field}")
    if not allow_empty and not items:
        raise SkillDrillExportError(f"skill drill export list must not be empty: {field}")
    return items


def _optional_string_list(mapping: dict[str, Any], field: str) -> list[str]:
    value = mapping.get(field, [])
    if not isinstance(value, list):
        raise SkillDrillExportError(f"skill drill export optional list field must be a list: {field}")
    items = [item for item in value if isinstance(item, str) and item]
    if len(items) != len(value):
        raise SkillDrillExportError(f"skill drill export optional list must contain only non-empty strings: {field}")
    return items


def _required_mapping_list(mapping: dict[str, Any], field: str) -> list[dict[str, Any]]:
    value = mapping.get(field)
    if not isinstance(value, list):
        raise SkillDrillExportError(f"skill drill export missing required list field: {field}")
    items = [item for item in value if isinstance(item, dict)]
    if len(items) != len(value):
        raise SkillDrillExportError(f"skill drill export list must contain only mappings: {field}")
    if not items:
        raise SkillDrillExportError(f"skill drill export list must not be empty: {field}")
    return items
