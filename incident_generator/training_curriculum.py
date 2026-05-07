"""Training curriculum ordering for benchmark-derived skill drills."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .benchmark_result_helpers import (
    display_path as _display_path,
    resolve_path as _resolve_path,
    source_ref as _source_ref,
)
from .parsers import load_yaml


TRAINING_CURRICULUM_SCHEMA_VERSION = "incident-generator.training-curriculum/v1"
DEFAULT_TRAINING_CURRICULUM_RELATIVE = Path("harness/training-curriculum-order.yaml")
DEFAULT_GOLDEN_RESPONSE_SEEDS_RELATIVE = Path("harness/golden-response-seeds.yaml")
DEFAULT_INCORRECT_RESPONSE_SEEDS_RELATIVE = Path("harness/incorrect-response-seeds.yaml")
DIFFICULTY_ORDER = ("beginner", "intermediate", "advanced")


class TrainingCurriculumError(ValueError):
    """Raised when training curriculum metadata is inconsistent."""


def build_training_curriculum(
    root: Path,
    *,
    curriculum_path: Path = DEFAULT_TRAINING_CURRICULUM_RELATIVE,
    golden_seeds_path: Path = DEFAULT_GOLDEN_RESPONSE_SEEDS_RELATIVE,
    incorrect_seeds_path: Path = DEFAULT_INCORRECT_RESPONSE_SEEDS_RELATIVE,
) -> dict[str, Any]:
    """Return a validated curriculum summary for checked training seeds."""

    root = root.resolve()
    curriculum_path = _resolve_path(root, curriculum_path)
    golden_path = _resolve_path(root, golden_seeds_path)
    incorrect_path = _resolve_path(root, incorrect_seeds_path)

    curriculum = load_yaml(curriculum_path)
    golden_manifest = load_yaml(golden_path)
    incorrect_manifest = load_yaml(incorrect_path)

    if _required_string(curriculum, "schema_version") != TRAINING_CURRICULUM_SCHEMA_VERSION:
        raise TrainingCurriculumError(f"unsupported curriculum schema: {curriculum.get('schema_version')}")
    release = _required_string(curriculum, "release")
    if _required_string(golden_manifest, "release") != release:
        raise TrainingCurriculumError("curriculum release does not match golden response seeds")
    if _required_string(incorrect_manifest, "release") != release:
        raise TrainingCurriculumError("curriculum release does not match incorrect response seeds")

    seed_rows = _required_mapping_list(golden_manifest, "seeds")
    seed_by_id = {_required_string(seed, "id"): seed for seed in seed_rows}
    incorrect_by_id = {
        _required_string(example, "id"): example
        for example in _required_mapping_list(incorrect_manifest, "examples")
    }

    declared_order = tuple(_required_string_list(curriculum, "difficulty_order"))
    if declared_order != DIFFICULTY_ORDER:
        raise TrainingCurriculumError(
            "curriculum difficulty_order must be: " + ", ".join(DIFFICULTY_ORDER)
        )

    levels: list[dict[str, Any]] = []
    entries: list[dict[str, Any]] = []
    seen_seed_ids: set[str] = set()
    seen_orders: set[int] = set()
    seen_difficulties: set[str] = set()

    for level in _required_mapping_list(curriculum, "levels"):
        difficulty = _required_string(level, "difficulty")
        if difficulty not in DIFFICULTY_ORDER:
            raise TrainingCurriculumError(f"unknown curriculum difficulty: {difficulty}")
        if difficulty in seen_difficulties:
            raise TrainingCurriculumError(f"duplicate curriculum difficulty: {difficulty}")
        seen_difficulties.add(difficulty)

        level_domains: list[dict[str, Any]] = []
        level_entry_count = 0
        seen_level_domains: set[str] = set()
        for domain_group in _required_mapping_list(level, "domains"):
            domain = _required_string(domain_group, "domain")
            if domain in seen_level_domains:
                raise TrainingCurriculumError(f"{difficulty} has duplicate domain: {domain}")
            seen_level_domains.add(domain)

            golden_seed_ids: list[str] = []
            for item in _required_mapping_list(domain_group, "items"):
                row = _curriculum_entry(
                    item,
                    difficulty=difficulty,
                    domain=domain,
                    seed_by_id=seed_by_id,
                    incorrect_by_id=incorrect_by_id,
                    seen_seed_ids=seen_seed_ids,
                    seen_orders=seen_orders,
                )
                golden_seed_ids.append(row["golden_seed_id"])
                entries.append(row)
                level_entry_count += 1
            level_domains.append(
                {
                    "domain": domain,
                    "entry_count": len(golden_seed_ids),
                    "golden_seed_ids": golden_seed_ids,
                }
            )

        levels.append(
            {
                "difficulty": difficulty,
                "title": _required_string(level, "title"),
                "description": _required_string(level, "description"),
                "entry_count": level_entry_count,
                "domains": level_domains,
            }
        )

    if tuple(level["difficulty"] for level in levels) != DIFFICULTY_ORDER:
        raise TrainingCurriculumError(
            "curriculum levels must appear in difficulty_order: " + ", ".join(DIFFICULTY_ORDER)
        )
    missing_seed_ids = sorted(set(seed_by_id) - seen_seed_ids)
    if missing_seed_ids:
        raise TrainingCurriculumError("curriculum is missing golden seeds: " + ", ".join(missing_seed_ids))
    if len(seen_seed_ids) != len(seed_by_id):
        raise TrainingCurriculumError("curriculum must list each golden seed exactly once")

    entries.sort(key=lambda row: row["order"])
    expected_orders = list(range(1, len(entries) + 1))
    if [row["order"] for row in entries] != expected_orders:
        raise TrainingCurriculumError(f"curriculum orders must be contiguous: {expected_orders}")
    _validate_prerequisites(entries)

    return {
        "schema_version": TRAINING_CURRICULUM_SCHEMA_VERSION,
        "release": release,
        "description": _required_string(curriculum, "description"),
        "source_refs": [
            _source_ref(curriculum_path, _display_path(root, curriculum_path)),
            _source_ref(golden_path, _display_path(root, golden_path)),
            _source_ref(incorrect_path, _display_path(root, incorrect_path)),
        ],
        "difficulty_order": list(DIFFICULTY_ORDER),
        "level_count": len(levels),
        "domain_count": len({entry["domain"] for entry in entries}),
        "entry_count": len(entries),
        "golden_seed_count": len(seed_by_id),
        "incorrect_response_count": len(incorrect_by_id),
        "validation_commands": _required_string_list(curriculum, "default_validation_commands"),
        "levels": levels,
        "entries": entries,
    }


def _curriculum_entry(
    item: dict[str, Any],
    *,
    difficulty: str,
    domain: str,
    seed_by_id: dict[str, dict[str, Any]],
    incorrect_by_id: dict[str, dict[str, Any]],
    seen_seed_ids: set[str],
    seen_orders: set[int],
) -> dict[str, Any]:
    order = _required_int(item, "order")
    if order in seen_orders:
        raise TrainingCurriculumError(f"duplicate curriculum order: {order}")
    seen_orders.add(order)

    golden_seed_id = _required_string(item, "golden_seed_id")
    seed = seed_by_id.get(golden_seed_id)
    if seed is None:
        raise TrainingCurriculumError(f"curriculum references unknown golden seed: {golden_seed_id}")
    if golden_seed_id in seen_seed_ids:
        raise TrainingCurriculumError(f"curriculum repeats golden seed: {golden_seed_id}")
    seen_seed_ids.add(golden_seed_id)

    scenario_ids = _required_string_list(seed, "scenario_ids")
    derived_domains = {_scenario_domain(scenario_id) for scenario_id in scenario_ids}
    if derived_domains != {domain}:
        raise TrainingCurriculumError(
            f"{golden_seed_id} domain {domain} does not match scenarios: {', '.join(sorted(derived_domains))}"
        )

    paired_negative_ids = _required_string_list(item, "paired_negative_ids", allow_empty=True)
    for negative_id in paired_negative_ids:
        negative = incorrect_by_id.get(negative_id)
        if negative is None:
            raise TrainingCurriculumError(f"{golden_seed_id} references unknown negative: {negative_id}")
        if _required_string(negative, "golden_seed_id") != golden_seed_id:
            raise TrainingCurriculumError(f"{negative_id} is not paired with {golden_seed_id}")

    prerequisites = _required_string_list(item, "prerequisite_seed_ids", allow_empty=True)
    for prerequisite in prerequisites:
        if prerequisite not in seed_by_id:
            raise TrainingCurriculumError(f"{golden_seed_id} references unknown prerequisite: {prerequisite}")
        if prerequisite == golden_seed_id:
            raise TrainingCurriculumError(f"{golden_seed_id} cannot require itself")

    return {
        "order": order,
        "difficulty": difficulty,
        "domain": domain,
        "golden_seed_id": golden_seed_id,
        "title": _required_string(seed, "title"),
        "release_alias": _required_string(seed, "release_alias"),
        "benchmark_set_id": _required_string(seed, "benchmark_set_id"),
        "drill_type": _required_string(seed, "drill_type"),
        "scenario_ids": scenario_ids,
        "learning_objective": _required_string(item, "learning_objective"),
        "prerequisite_seed_ids": prerequisites,
        "paired_negative_ids": paired_negative_ids,
    }


def _validate_prerequisites(entries: list[dict[str, Any]]) -> None:
    order_by_seed = {entry["golden_seed_id"]: entry["order"] for entry in entries}
    for entry in entries:
        late_prerequisites = [
            prerequisite
            for prerequisite in entry["prerequisite_seed_ids"]
            if order_by_seed[prerequisite] >= entry["order"]
        ]
        if late_prerequisites:
            raise TrainingCurriculumError(
                f"{entry['golden_seed_id']} prerequisites must appear earlier: "
                + ", ".join(late_prerequisites)
            )


def _scenario_domain(scenario_id: str) -> str:
    if "-" not in scenario_id:
        raise TrainingCurriculumError(f"scenario id does not include a domain prefix: {scenario_id}")
    return scenario_id.split("-", 1)[0]


def _required_string(mapping: dict[str, Any], field: str) -> str:
    value = mapping.get(field)
    if not isinstance(value, str) or not value:
        raise TrainingCurriculumError(f"training curriculum missing required string field: {field}")
    return value


def _required_int(mapping: dict[str, Any], field: str) -> int:
    value = mapping.get(field)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise TrainingCurriculumError(f"training curriculum missing positive integer field: {field}")
    return value


def _required_string_list(mapping: dict[str, Any], field: str, *, allow_empty: bool = False) -> list[str]:
    value = mapping.get(field)
    if not isinstance(value, list):
        raise TrainingCurriculumError(f"training curriculum missing required list field: {field}")
    items = [item for item in value if isinstance(item, str) and item]
    if len(items) != len(value):
        raise TrainingCurriculumError(f"training curriculum list must contain only non-empty strings: {field}")
    if not allow_empty and not items:
        raise TrainingCurriculumError(f"training curriculum list must not be empty: {field}")
    return items


def _required_mapping_list(mapping: dict[str, Any], field: str) -> list[dict[str, Any]]:
    value = mapping.get(field)
    if not isinstance(value, list):
        raise TrainingCurriculumError(f"training curriculum missing required list field: {field}")
    items = [item for item in value if isinstance(item, dict)]
    if len(items) != len(value):
        raise TrainingCurriculumError(f"training curriculum list must contain only mappings: {field}")
    if not items:
        raise TrainingCurriculumError(f"training curriculum list must not be empty: {field}")
    return items
