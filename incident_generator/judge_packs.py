"""Judge-pack definitions for benchmark result emission."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from .benchmark_result_helpers import (
    relative_path as _relative_path,
    resolve_path as _resolve_path,
    sha256_file as _sha256_file,
)
from .parsers import load_yaml


DEFAULT_AGENT_ADAPTER_JUDGE_PACKS_RELATIVE = Path("harness/agent-adapter-judge-packs.yaml")
JUDGE_PACK_SCHEMA_VERSION = "incident-generator.judge-packs/v1"
JUDGE_PACK_KINDS = {"deterministic", "llm_tier2", "mixed"}
JUDGE_PACK_SELECTION_STATUSES = {"executable", "planned_fail_closed"}
JUDGE_PACK_EXECUTION_MODES = {"local", "external", "mixed"}


class JudgePackError(ValueError):
    """Raised when judge-pack metadata is missing or invalid."""


def load_judge_pack_report(
    root: Path,
    *,
    judge_packs_path: Path = DEFAULT_AGENT_ADAPTER_JUDGE_PACKS_RELATIVE,
    pack_id: str | None = None,
) -> dict[str, Any]:
    """Load and validate the checked judge-pack manifest."""

    resolved_path = _resolve_path(root, judge_packs_path)
    manifest = _load_manifest(resolved_path)
    packs = _validated_packs(manifest)
    if pack_id is not None:
        packs = [pack for pack in packs if pack["id"] == pack_id]
        if not packs:
            raise JudgePackError(f"unknown judge pack: {pack_id}")
    return {
        "schema_version": JUDGE_PACK_SCHEMA_VERSION,
        "source_ref": {
            "kind": "harness_plan",
            "ref": _relative_path(root, resolved_path),
            "sha256": _sha256_file(resolved_path),
            "notes": "agent adapter judge-pack manifest",
        },
        "pack_count": len(packs),
        "selected_pack_id": pack_id,
        "packs": packs,
    }


def select_judge_pack(
    root: Path,
    pack_id: str,
    *,
    judge_packs_path: Path = DEFAULT_AGENT_ADAPTER_JUDGE_PACKS_RELATIVE,
) -> dict[str, Any]:
    """Return one validated judge pack by id."""

    report = load_judge_pack_report(root, judge_packs_path=judge_packs_path, pack_id=pack_id)
    return dict(report["packs"][0])


def _load_manifest(path: Path) -> Mapping[str, Any]:
    payload = load_yaml(path)
    if not isinstance(payload, Mapping):
        raise JudgePackError("judge-pack manifest must be a YAML object")
    schema_version = _required_string(payload, "schema_version")
    if schema_version != JUDGE_PACK_SCHEMA_VERSION:
        raise JudgePackError(f"unsupported judge-pack schema_version: {schema_version}")
    return payload


def _validated_packs(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    raw_packs = manifest.get("packs")
    if not isinstance(raw_packs, list) or not raw_packs:
        raise JudgePackError("judge-pack manifest must contain at least one pack")
    packs: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw_pack in enumerate(raw_packs):
        if not isinstance(raw_pack, Mapping):
            raise JudgePackError(f"judge-pack packs[{index}] must be an object")
        pack_id = _required_string(raw_pack, "id")
        if pack_id in seen_ids:
            raise JudgePackError(f"duplicate judge pack id: {pack_id}")
        seen_ids.add(pack_id)
        judge_kind = _enum_string(raw_pack, "judge_kind", JUDGE_PACK_KINDS)
        selection_status = _enum_string(raw_pack, "selection_status", JUDGE_PACK_SELECTION_STATUSES)
        execution_mode = _enum_string(raw_pack, "execution_mode", JUDGE_PACK_EXECUTION_MODES)
        separate_family_required = _bool(raw_pack, "separate_family_required")
        requires_live_provider = _bool(raw_pack, "requires_live_provider")
        if judge_kind in {"llm_tier2", "mixed"} and not separate_family_required:
            raise JudgePackError(f"{pack_id} must require separate model families")
        if selection_status == "executable" and requires_live_provider:
            raise JudgePackError(f"{pack_id} cannot be executable while requiring a live provider")
        packs.append(
            {
                "id": pack_id,
                "name": _required_string(raw_pack, "name"),
                "description": _required_string(raw_pack, "description"),
                "judge_kind": judge_kind,
                "selection_status": selection_status,
                "execution_mode": execution_mode,
                "separate_family_required": separate_family_required,
                "requires_live_provider": requires_live_provider,
                "deterministic_gate": _required_string(raw_pack, "deterministic_gate"),
                "result_behavior": _required_string(raw_pack, "result_behavior"),
                "required_env": _string_list(raw_pack.get("required_env", []), field=f"{pack_id}.required_env"),
                "artifacts": _string_list(raw_pack.get("artifacts", []), field=f"{pack_id}.artifacts"),
            }
        )
    return packs


def _enum_string(payload: Mapping[str, Any], field: str, allowed: set[str]) -> str:
    value = _required_string(payload, field)
    if value not in allowed:
        raise JudgePackError(f"unsupported {field}: {value}")
    return value


def _required_string(payload: Mapping[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise JudgePackError(f"judge-pack field must be a non-empty string: {field}")
    return value.strip()


def _bool(payload: Mapping[str, Any], field: str) -> bool:
    value = payload.get(field)
    if not isinstance(value, bool):
        raise JudgePackError(f"judge-pack field must be boolean: {field}")
    return value


def _string_list(value: Any, *, field: str) -> list[str]:
    if not isinstance(value, list):
        raise JudgePackError(f"judge-pack field must be a string list: {field}")
    rows: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise JudgePackError(f"judge-pack field must contain non-empty strings: {field}[{index}]")
        rows.append(item.strip())
    return rows
