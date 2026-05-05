"""Release manifest generation for incident-generator artifacts."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .scenarios import build_catalog_report


MANIFEST_API_VERSION = "incident-generator-release/v1alpha1"
SCENARIO_SCHEMA_VERSION = "sre-agent-scenario/v1alpha1"


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
        "artifacts": _artifact_checksums(root, artifact_dir),
    }


def write_release_manifest(root: Path, output: Path, *, artifact_dir: Path | None = None) -> dict[str, Any]:
    manifest = build_release_manifest(root, artifact_dir=artifact_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


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


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
