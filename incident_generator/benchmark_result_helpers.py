"""Shared helpers for incident-generator JSON payload builders."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, TypeVar


ErrorT = TypeVar("ErrorT", bound=ValueError)


def artifact_ref(root: Path, path: Path, kind: str, *, notes: str) -> dict[str, str | None]:
    return {
        "kind": kind,
        "ref": relative_path(root, path),
        "sha256": sha256_file(path) if path.is_file() else None,
        "notes": notes,
    }


def load_json_object(
    path: Path,
    *,
    error_cls: type[ErrorT] = ValueError,
    invalid_message: str | None = None,
    object_message: str | None = None,
) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        message = invalid_message.format(path=path, error=exc) if invalid_message else f"invalid JSON in {path}: {exc}"
        raise error_cls(message) from exc
    if not isinstance(payload, dict):
        message = object_message.format(path=path) if object_message else f"{path} must contain a JSON object"
        raise error_cls(message)
    return payload


def write_json_file(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def resolve_path(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def relative_path(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def display_path(root: Path, path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError:
        return resolved.as_posix()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def sha256_tree(path: Path) -> str:
    digest = hashlib.sha256()
    for child in sorted(item for item in path.rglob("*") if item.is_file()):
        digest.update(child.relative_to(path).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(child).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def source_ref(path: Path, display_path: str) -> dict[str, Any]:
    if path.is_file():
        return {"path": display_path, "kind": "file", "sha256": sha256_file(path)}
    if path.is_dir():
        return {"path": display_path, "kind": "directory", "sha256": sha256_tree(path)}
    return {"path": display_path, "kind": "missing", "sha256": ""}


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def stable_hash(payload: Mapping[str, Any], *, hash_key: str = "artifact_hash") -> str:
    clean = {key: value for key, value in payload.items() if key != hash_key}
    return sha256_text(canonical_json(clean))


def mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def string(value: Any) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""


def string_list(value: Any) -> list[str]:
    if isinstance(value, str) and value:
        return [value]
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def append_unique(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


def unique_refs(refs: list[dict[str, str | None]]) -> list[dict[str, str | None]]:
    unique: list[dict[str, str | None]] = []
    seen: set[tuple[str | None, str | None]] = set()
    for ref in refs:
        key = (ref.get("kind"), ref.get("ref"))
        if key in seen:
            continue
        seen.add(key)
        unique.append(ref)
    return unique


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
