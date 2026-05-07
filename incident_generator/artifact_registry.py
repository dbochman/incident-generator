"""Benchmark artifact registry writer for incident-generator runs."""

from __future__ import annotations

import json
import os
import platform
import re
import shlex
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from .benchmark_result_helpers import (
    canonical_json as _canonical_json,
    load_json_object as _shared_load_json_object,
    sha256_file as _sha256_file,
    sha256_text as _sha256_text,
    utc_now as _utc_timestamp,
    write_json_file as _write_json_file,
)
from .parsers import load_yaml


REGISTRY_SCHEMA_VERSION = "incident-generator.artifact-registry/v1"
BACKFILL_SCHEMA_VERSION = "incident-generator.artifact-registry-backfill-plan/v1"
HASH_ALGORITHM = "sha256"
FAILURE_CLASSES = {
    "none",
    "resource_collision",
    "seed_predicate_runtime_issue",
    "adapter_runtime_issue",
    "agent_hypothesis_regression",
    "validation_issue",
    "mixed",
}
STATES = {"passed", "generated", "blocked", "failed", "partial", "unknown"}
ARCHETYPES = {"fixture", "kind", "linux-vm", "mixed", "unknown"}
COLLECTION_MODES = {"fixture", "real"}
DOCKER_HOST_KINDS = {"local", "ssh", "none", "unknown"}
REQUIRED_ARTIFACTS = {
    "result_json": "result.json",
    "events_ndjson": "events.ndjson",
    "summary_json": "summary.json",
}
OPTIONAL_ARTIFACTS = {
    "dashboard_json": "dashboard.json",
    "dashboard_markdown": "dashboard.md",
    "noisy_smoke_report_json": "noisy-smoke-report.json",
    "loadgen_preview_json": "loadgen-preview.json",
    "cleanup_summary_json": "cleanup-summary.json",
}
SENSITIVE_ENV_PATTERN = re.compile(
    r"(TOKEN|SECRET|PASSWORD|CREDENTIAL|PRIVATE|AUTH|COOKIE|SESSION|API[_-]?KEY|KUBECONFIG)",
    re.IGNORECASE,
)
TIMEOUT_ENV_KEYS = {
    "SRE_AGENT_KIND_WAIT",
    "SRE_AGENT_KIND_API_WAIT_SECONDS",
    "SRE_AGENT_KIND_CREATE_TIMEOUT_SECONDS",
    "SRE_AGENT_REMOTE_DOCKER_TIMEOUT_SECONDS",
    "SRE_AGENT_OBSERVABILITY_TIMEOUT",
    "SRE_AGENT_HELM_TIMEOUT",
    "SRE_AGENT_MISBEHAVING_APP_HELM_TIMEOUT",
    "SRE_AGENT_TLS_TARGET_HELM_TIMEOUT",
    "SRE_AGENT_DNS_TLS_PROBE_TIMEOUT",
    "SRE_AGENT_COREDNS_ROLLOUT_TIMEOUT",
    "SRE_AGENT_SCENARIO_WAIT_TIMEOUT",
}
REGISTRY_TOP_LEVEL_FIELDS = {"schema_version", "created_at", "entries"}
REGISTRY_ENTRY_REQUIRED_FIELDS = {
    "run_id",
    "benchmark_set_id",
    "seed",
    "scenario_ids",
    "combination_size",
    "archetype",
    "collection_mode",
    "host_profile",
    "command",
    "environment_fingerprint",
    "retained_paths",
    "content_hashes",
    "state",
    "failure_class",
    "created_at",
}
REGISTRY_ENTRY_FIELDS = REGISTRY_ENTRY_REQUIRED_FIELDS | {
    "failure_classification",
    "agent_replay",
    "notes",
}
HOST_PROFILE_REQUIRED_FIELDS = {"profile_id", "docker_host_kind"}
HOST_PROFILE_FIELDS = HOST_PROFILE_REQUIRED_FIELDS | {
    "docker_host",
    "architecture",
    "cpu_count",
    "memory_bytes",
    "docker_data_root_free_bytes",
}
COMMAND_REQUIRED_FIELDS = {"argv"}
COMMAND_FIELDS = COMMAND_REQUIRED_FIELDS | {"cwd", "env"}
ENVIRONMENT_FINGERPRINT_REQUIRED_FIELDS = {"fingerprint_id"}
RETAINED_PATH_REQUIRED_FIELDS = set(REQUIRED_ARTIFACTS)
CONTENT_HASH_REQUIRED_FIELDS = {"algorithm", "value"}
HASH_VALUE_PATTERN = re.compile(r"^[a-f0-9]{64}$")


class ArtifactRegistryError(ValueError):
    """Raised when benchmark artifact registry input cannot be indexed."""


@dataclass(frozen=True)
class ArtifactRegistryFinding:
    severity: str
    rule: str
    path: str
    message: str
    json_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "severity": self.severity,
            "rule": self.rule,
            "path": self.path,
            "message": self.message,
        }
        if self.json_path is not None:
            payload["json_path"] = self.json_path
        return payload


def append_registry_entry(
    root: Path,
    *,
    registry_path: Path,
    artifact_dir: Path,
    benchmark_set_id: str,
    command: str,
    command_cwd: str | None = ".",
    run_id: str | None = None,
    seed: int | None = None,
    env: dict[str, str | None] | None = None,
    host_profile: str = "unknown",
    docker_host_kind: str | None = None,
    docker_host: str | None = None,
    architecture: str | None = None,
    cpu_count: int | None = None,
    memory_bytes: int | None = None,
    docker_data_root_free_bytes: int | None = None,
    agent_replay_summary: Path | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Append one registry entry and return the updated registry document."""

    root = root.resolve()
    registry_path = _resolve(root, registry_path)
    entry = build_registry_entry(
        root,
        registry_path=registry_path,
        artifact_dir=artifact_dir,
        benchmark_set_id=benchmark_set_id,
        command=command,
        command_cwd=command_cwd,
        run_id=run_id,
        seed=seed,
        env=env,
        host_profile=host_profile,
        docker_host_kind=docker_host_kind,
        docker_host=docker_host,
        architecture=architecture,
        cpu_count=cpu_count,
        memory_bytes=memory_bytes,
        docker_data_root_free_bytes=docker_data_root_free_bytes,
        agent_replay_summary=agent_replay_summary,
        created_at=created_at,
    )
    registry = _load_registry(registry_path, created_at=created_at)
    entries = registry["entries"]
    if any(isinstance(item, dict) and item.get("run_id") == entry["run_id"] for item in entries):
        raise ArtifactRegistryError(f"registry already contains run_id: {entry['run_id']}")
    entries.append(entry)
    _write_json_file(registry_path, registry)
    return registry


def build_registry_entry(
    root: Path,
    *,
    registry_path: Path,
    artifact_dir: Path,
    benchmark_set_id: str,
    command: str,
    command_cwd: str | None = ".",
    run_id: str | None = None,
    seed: int | None = None,
    env: dict[str, str | None] | None = None,
    host_profile: str = "unknown",
    docker_host_kind: str | None = None,
    docker_host: str | None = None,
    architecture: str | None = None,
    cpu_count: int | None = None,
    memory_bytes: int | None = None,
    docker_data_root_free_bytes: int | None = None,
    agent_replay_summary: Path | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    artifact_dir = _resolve(root, artifact_dir)
    created_at = created_at or _utc_timestamp()
    result_path = artifact_dir / REQUIRED_ARTIFACTS["result_json"]
    result = _load_required_json(result_path)
    summary_path = artifact_dir / REQUIRED_ARTIFACTS["summary_json"]
    _load_required_json(summary_path)
    events_path = artifact_dir / REQUIRED_ARTIFACTS["events_ndjson"]
    _require_file(events_path)

    retained_files = {
        "result_json": result_path,
        "events_ndjson": events_path,
        "summary_json": summary_path,
    }
    for key, filename in OPTIONAL_ARTIFACTS.items():
        path = artifact_dir / filename
        if path.is_file():
            retained_files[key] = path
    replay_summary_payload = None
    if agent_replay_summary is not None:
        replay_path = _resolve(root, agent_replay_summary)
        replay_summary_payload = _load_required_json(replay_path)
        retained_files["agent_replay_summary_json"] = replay_path

    parsed_env = env or {}
    redacted_env = {key: _redact_env_value(key, value) for key, value in sorted(parsed_env.items())}
    collection_mode = _collection_mode(result)
    docker_host = docker_host if docker_host is not None else _docker_host_from_env_or_result(parsed_env, result)
    docker_host_kind = _docker_host_kind(collection_mode, docker_host_kind, docker_host)
    host = {
        "profile_id": host_profile or "unknown",
        "docker_host_kind": docker_host_kind,
        "docker_host": docker_host,
        "architecture": architecture or platform.machine() or None,
        "cpu_count": cpu_count if cpu_count is not None else os.cpu_count(),
        "memory_bytes": memory_bytes,
        "docker_data_root_free_bytes": docker_data_root_free_bytes,
    }
    environment_fingerprint = _environment_fingerprint(
        result,
        redacted_env=redacted_env,
        docker_host=docker_host,
        architecture=host["architecture"],
    )
    scenario_ids = _scenario_ids(result)
    entry = {
        "run_id": run_id or _default_run_id(artifact_dir, result),
        "benchmark_set_id": _required_text(benchmark_set_id, "benchmark_set_id"),
        "seed": seed if seed is not None else _result_seed(result),
        "scenario_ids": scenario_ids,
        "combination_size": _combination_size(result, scenario_ids),
        "archetype": _archetype(result),
        "collection_mode": collection_mode,
        "host_profile": host,
        "command": {
            "argv": _command_argv(command),
            "cwd": command_cwd,
            "env": redacted_env,
        },
        "environment_fingerprint": environment_fingerprint,
        "retained_paths": {
            key: _display_path(root, registry_path, path)
            for key, path in sorted(retained_files.items())
        },
        "content_hashes": {
            key: {"algorithm": HASH_ALGORITHM, "value": _sha256_file(path)}
            for key, path in sorted(retained_files.items())
        },
        "state": _state(result, replay_summary_payload),
        "failure_class": _failure_class(result, replay_summary_payload),
        "failure_classification": result.get("failure_classification") if isinstance(result, dict) else None,
        "agent_replay": _agent_replay_summary(replay_summary_payload),
        "created_at": created_at,
    }
    _validate_entry(entry)
    return entry


def backfill_registry_payload(
    root: Path,
    *,
    manifest_path: Path,
    registry_path: Path,
    write: bool = False,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build or append registry entries from a checked backfill manifest."""

    root = root.resolve()
    manifest_path = _resolve(root, manifest_path)
    registry_path = _resolve(root, registry_path)
    findings: list[ArtifactRegistryFinding] = []
    candidates: list[dict[str, Any]] = []

    try:
        manifest = load_yaml(manifest_path)
    except (OSError, ValueError) as exc:
        findings.append(_registry_finding(manifest_path, "$", "manifest-yaml", str(exc)))
        manifest = {}
    if not isinstance(manifest, dict):
        findings.append(_registry_finding(manifest_path, "$", "type", "manifest must be a mapping"))
        manifest = {}

    manifest_created_at = created_at or _optional_text(manifest.get("created_at")) or _utc_timestamp()
    if manifest.get("schema_version") != BACKFILL_SCHEMA_VERSION:
        findings.append(
            _registry_finding(
                manifest_path,
                "$.schema_version",
                "schema-version",
                f"schema_version must be {BACKFILL_SCHEMA_VERSION}",
            )
        )
    if manifest.get("hash_algorithm") != HASH_ALGORITHM:
        findings.append(
            _registry_finding(manifest_path, "$.hash_algorithm", "hash-algorithm", "hash_algorithm must be sha256")
        )

    try:
        registry = _load_registry(registry_path, created_at=manifest_created_at)
    except ArtifactRegistryError as exc:
        findings.append(_registry_finding(registry_path, "$", "registry-json", str(exc)))
        registry = {"schema_version": REGISTRY_SCHEMA_VERSION, "created_at": manifest_created_at, "entries": []}

    entries = manifest.get("entries")
    if not isinstance(entries, list):
        findings.append(_registry_finding(manifest_path, "$.entries", "type", "entries must be an array"))
        entries = []
    restore_required_entries = manifest.get("restore_required_entries") or []
    if not isinstance(restore_required_entries, list):
        findings.append(
            _registry_finding(
                manifest_path,
                "$.restore_required_entries",
                "type",
                "restore_required_entries must be an array when provided",
            )
        )
        restore_required_entries = []
    for index, restore_entry in enumerate(restore_required_entries):
        run_id = restore_entry.get("run_id") if isinstance(restore_entry, dict) else None
        suffix = f": {run_id}" if isinstance(run_id, str) and run_id else ""
        findings.append(
            _registry_finding(
                manifest_path,
                f"$.restore_required_entries[{index}]",
                "restore-required",
                "backfill manifest still contains a restore-required entry"
                f"{suffix}; restore its artifacts or move it to excluded_sources before dry-run/write",
            )
        )
    excluded_sources = manifest.get("excluded_sources") or []
    if not isinstance(excluded_sources, list):
        findings.append(
            _registry_finding(
                manifest_path,
                "$.excluded_sources",
                "type",
                "excluded_sources must be an array when provided",
            )
        )
        excluded_sources = []

    existing_run_ids = {
        str(entry.get("run_id"))
        for entry in registry.get("entries", [])
        if isinstance(entry, dict) and isinstance(entry.get("run_id"), str)
    }
    seen_manifest_run_ids: dict[str, int] = {}
    for index, entry in enumerate(entries):
        entry_path = f"$.entries[{index}]"
        if not isinstance(entry, dict):
            findings.append(_registry_finding(manifest_path, entry_path, "type", "entry must be an object"))
            continue
        run_id = _optional_text(entry.get("run_id"))
        if run_id is None:
            findings.append(_registry_finding(manifest_path, f"{entry_path}.run_id", "required-field", "run_id is required"))
            continue
        if run_id in seen_manifest_run_ids:
            findings.append(
                _registry_finding(
                    manifest_path,
                    f"{entry_path}.run_id",
                    "duplicate-run-id",
                    f"duplicate run_id also appears at $.entries[{seen_manifest_run_ids[run_id]}]",
                )
            )
            continue
        seen_manifest_run_ids[run_id] = index
        if run_id in existing_run_ids:
            findings.append(
                _registry_finding(
                    manifest_path,
                    f"{entry_path}.run_id",
                    "duplicate-run-id",
                    f"registry already contains run_id: {run_id}",
                )
            )
            continue
        before_error_count = _error_count(findings)
        findings.extend(_validate_backfill_hashes(root, manifest_path, entry, entry_path))
        if _error_count(findings) != before_error_count:
            continue
        try:
            candidate = _build_backfill_candidate(
                root,
                registry_path=registry_path,
                manifest_entry=entry,
                created_at=manifest_created_at,
            )
        except ArtifactRegistryError as exc:
            findings.append(_registry_finding(manifest_path, entry_path, "entry-build", str(exc)))
            continue
        findings.extend(_validate_backfill_expectations(root, manifest_path, entry, candidate, entry_path))
        candidates.append(candidate)

    payload = {
        "ok": _error_count(findings) == 0,
        "schema_version": "incident-generator.artifact-registry-backfill/v1",
        "manifest": str(manifest_path),
        "registry": str(registry_path),
        "dry_run": not write,
        "write": write,
        "existing_entry_count": len(registry.get("entries", [])),
        "candidate_entry_count": len(candidates),
        "restore_required_count": len(restore_required_entries),
        "excluded_source_count": len(excluded_sources),
        "error_count": _error_count(findings),
        "warning_count": sum(1 for finding in findings if finding.severity == "warning"),
        "findings": [finding.to_dict() for finding in findings],
        "entries": candidates,
    }
    if write:
        if not payload["ok"]:
            return payload
        updated_registry = {
            "schema_version": registry["schema_version"],
            "created_at": registry["created_at"],
            "entries": list(registry.get("entries", [])) + candidates,
        }
        _write_json_file(registry_path, updated_registry)
        check_findings = check_registry(root, registry_path=registry_path)
        payload["registry_entry_count"] = len(updated_registry["entries"])
        payload["post_write_error_count"] = _error_count(check_findings)
        payload["post_write_warning_count"] = sum(1 for finding in check_findings if finding.severity == "warning")
        payload["post_write_findings"] = [finding.to_dict() for finding in check_findings]
        payload["ok"] = payload["post_write_error_count"] == 0
    return payload


def parse_env_assignments(values: list[str] | None) -> dict[str, str | None]:
    env: dict[str, str | None] = {}
    for value in values or []:
        if "=" not in value:
            raise ArtifactRegistryError(f"--env must be KEY=VALUE: {value}")
        key, raw = value.split("=", 1)
        key = key.strip()
        if not key:
            raise ArtifactRegistryError("--env key must not be empty")
        env[key] = raw
    return env


def check_registry(root: Path, *, registry_path: Path) -> list[ArtifactRegistryFinding]:
    """Return validation findings for one benchmark artifact registry."""

    root = root.resolve()
    registry_path = _resolve(root, registry_path)
    try:
        registry = _load_json_document(registry_path, label="registry")
    except ArtifactRegistryError as exc:
        return [_registry_finding(registry_path, "$", "registry-json", str(exc))]
    findings = _validate_registry_document(registry_path, registry)
    entries = registry.get("entries") if isinstance(registry, dict) else None
    if not isinstance(entries, list):
        return findings
    seen_run_ids: dict[str, int] = {}
    for index, entry in enumerate(entries):
        json_path = f"$.entries[{index}]"
        if not isinstance(entry, dict):
            findings.append(_registry_finding(registry_path, json_path, "type", "entry must be an object"))
            continue
        run_id = entry.get("run_id")
        if isinstance(run_id, str) and run_id:
            if run_id in seen_run_ids:
                findings.append(
                    _registry_finding(
                        registry_path,
                        f"{json_path}.run_id",
                        "duplicate-run-id",
                        f"duplicate run_id also appears at $.entries[{seen_run_ids[run_id]}]",
                    )
                )
            else:
                seen_run_ids[run_id] = index
        findings.extend(_validate_registry_entry_document(root, registry_path, entry, json_path))
        findings.extend(_validate_retained_artifacts(root, registry_path, entry, json_path))
    return findings


def registry_check_payload(root: Path, *, registry_path: Path) -> dict[str, Any]:
    registry_path = _resolve(root.resolve(), registry_path)
    findings = check_registry(root, registry_path=registry_path)
    entry_count = 0
    try:
        registry = _load_json_document(registry_path, label="registry")
        entries = registry.get("entries") if isinstance(registry, dict) else None
        if isinstance(entries, list):
            entry_count = len(entries)
    except ArtifactRegistryError:
        pass
    return {
        "ok": not any(finding.severity == "error" for finding in findings),
        "registry": str(registry_path),
        "entry_count": entry_count,
        "error_count": sum(1 for finding in findings if finding.severity == "error"),
        "warning_count": sum(1 for finding in findings if finding.severity == "warning"),
        "findings": [finding.to_dict() for finding in findings],
    }


def render_registry_markdown(root: Path, *, registry_path: Path) -> str:
    root = root.resolve()
    registry_path = _resolve(root, registry_path)
    payload = registry_check_payload(root, registry_path=registry_path)
    try:
        registry = _load_json_document(registry_path, label="registry")
    except ArtifactRegistryError:
        registry = {}
    entries = registry.get("entries") if isinstance(registry, dict) else []
    if not isinstance(entries, list):
        entries = []

    lines = [
        "# Incident Generator Artifact Registry",
        "",
        f"- Registry: `{_markdown_escape(_repo_relative_path(root, registry_path))}`",
        f"- Schema: `{_markdown_escape(str(registry.get('schema_version', 'unknown')) if isinstance(registry, dict) else 'unknown')}`",
        f"- Entries: {len(entries)}",
        f"- Check: {'pass' if payload['ok'] else 'fail'} ({payload['error_count']} errors, {payload['warning_count']} warnings)",
        "",
        "## Entries",
        "",
    ]
    if entries:
        lines.extend(
            [
                "| Run ID | Benchmark Set | Seed | Scenarios | Size | Mode | Host | State | Failure Class | Artifacts |",
                "| --- | --- | ---: | --- | ---: | --- | --- | --- | --- | ---: |",
            ]
        )
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            lines.append(_markdown_entry_row(entry))
    else:
        lines.append("No registry entries.")
    findings = payload["findings"]
    if findings:
        lines.extend(
            [
                "",
                "## Findings",
                "",
                "| Severity | Rule | JSON Path | Message |",
                "| --- | --- | --- | --- |",
            ]
        )
        for finding in findings:
            lines.append(
                "| {severity} | `{rule}` | `{json_path}` | {message} |".format(
                    severity=_markdown_escape(str(finding["severity"])),
                    rule=_markdown_escape(str(finding["rule"])),
                    json_path=_markdown_escape(str(finding.get("json_path", ""))),
                    message=_markdown_escape(str(finding["message"])),
                )
            )
    lines.append("")
    return "\n".join(lines)


def write_registry_markdown(root: Path, *, registry_path: Path, output: Path) -> str:
    markdown = render_registry_markdown(root, registry_path=registry_path)
    output = _resolve(root.resolve(), output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(markdown, encoding="utf-8")
    return markdown


def registry_markdown_check_payload(root: Path, *, registry_path: Path, output: Path) -> dict[str, Any]:
    markdown = render_registry_markdown(root, registry_path=registry_path)
    output = _resolve(root.resolve(), output)
    actual = output.read_text(encoding="utf-8") if output.is_file() else None
    return {
        "ok": actual == markdown,
        "output": str(output),
        "expected_sha256": _sha256_text(markdown),
        "actual_sha256": _sha256_text(actual) if actual is not None else None,
        "missing": actual is None,
    }


def _resolve(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _optional_text(value: Any) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None


def _load_json_document(path: Path, *, label: str) -> dict[str, Any]:
    _require_file(path)
    return _shared_load_json_object(
        path,
        error_cls=ArtifactRegistryError,
        invalid_message=f"{label} is not valid JSON: {{path}}: {{error}}",
        object_message=f"{label} must be a JSON object: {{path}}",
    )


def _load_registry(path: Path, *, created_at: str | None) -> dict[str, Any]:
    if not path.exists():
        return {"schema_version": REGISTRY_SCHEMA_VERSION, "created_at": created_at or _utc_timestamp(), "entries": []}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ArtifactRegistryError(f"registry is not valid JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ArtifactRegistryError("registry must be a JSON object")
    if payload.get("schema_version") != REGISTRY_SCHEMA_VERSION:
        raise ArtifactRegistryError(f"registry schema_version must be {REGISTRY_SCHEMA_VERSION}")
    if not isinstance(payload.get("entries"), list):
        raise ArtifactRegistryError("registry entries must be an array")
    return payload


def _load_required_json(path: Path) -> dict[str, Any]:
    _require_file(path)
    return _shared_load_json_object(
        path,
        error_cls=ArtifactRegistryError,
        invalid_message="artifact is not valid JSON: {path}: {error}",
        object_message="artifact JSON must be an object: {path}",
    )


def _require_file(path: Path) -> None:
    if not path.is_file():
        raise ArtifactRegistryError(f"required artifact is missing: {path}")


def _required_text(value: str, field: str) -> str:
    if not value:
        raise ArtifactRegistryError(f"{field} is required")
    return value


def _command_argv(command: str) -> list[str]:
    argv = shlex.split(_required_text(command, "command"))
    if not argv:
        raise ArtifactRegistryError("command must parse to at least one argv item")
    return argv


def _display_path(root: Path, registry_path: Path, path: Path) -> str:
    resolved = path.resolve()
    for base in (registry_path.resolve().parent, root.resolve()):
        try:
            return str(resolved.relative_to(base))
        except ValueError:
            continue
    return path.name


def _repo_relative_path(root: Path, path: Path) -> str:
    try:
        return str(path.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(path)


def _validate_backfill_hashes(
    root: Path,
    manifest_path: Path,
    entry: dict[str, Any],
    entry_path: str,
) -> list[ArtifactRegistryFinding]:
    findings: list[ArtifactRegistryFinding] = []
    required_hashes = entry.get("required_hashes")
    if not isinstance(required_hashes, dict) or not required_hashes:
        return [_registry_finding(manifest_path, f"{entry_path}.required_hashes", "type", "required_hashes must be an object")]
    for key, payload in sorted(required_hashes.items()):
        hash_path = f"{entry_path}.required_hashes.{key}"
        if not isinstance(payload, dict):
            findings.append(_registry_finding(manifest_path, hash_path, "type", "required hash entry must be an object"))
            continue
        relative_path = payload.get("path")
        expected_sha = payload.get("sha256")
        if not isinstance(relative_path, str) or not relative_path:
            findings.append(_registry_finding(manifest_path, f"{hash_path}.path", "type", "path must be a non-empty string"))
            continue
        if _unsafe_retained_path(relative_path):
            findings.append(
                _registry_finding(
                    manifest_path,
                    f"{hash_path}.path",
                    "unsafe-path",
                    "backfill artifact paths must be relative and cannot traverse parents",
                )
            )
            continue
        if not isinstance(expected_sha, str) or not HASH_VALUE_PATTERN.fullmatch(expected_sha):
            findings.append(
                _registry_finding(
                    manifest_path,
                    f"{hash_path}.sha256",
                    "content-hash",
                    "sha256 must be a 64-character lowercase hex digest",
                )
            )
            continue
        artifact_path = root / relative_path
        if not artifact_path.is_file():
            findings.append(
                _registry_finding(
                    manifest_path,
                    f"{hash_path}.path",
                    "artifact-missing",
                    f"backfill artifact is missing: {relative_path}",
                )
            )
            continue
        actual_sha = _sha256_file(artifact_path)
        if actual_sha != expected_sha:
            findings.append(
                _registry_finding(
                    manifest_path,
                    f"{hash_path}.sha256",
                    "artifact-hash",
                    f"backfill artifact hash drifted for {relative_path}",
                )
            )
    return findings


def _build_backfill_candidate(
    root: Path,
    *,
    registry_path: Path,
    manifest_entry: dict[str, Any],
    created_at: str,
) -> dict[str, Any]:
    command = manifest_entry.get("command")
    if not isinstance(command, dict):
        raise ArtifactRegistryError("command must be an object")
    argv = command.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(item, str) for item in argv):
        raise ArtifactRegistryError("command.argv must be a non-empty string array")
    env = command.get("env") or {}
    if not isinstance(env, dict) or not all(isinstance(key, str) for key in env):
        raise ArtifactRegistryError("command.env must be an object with string keys")
    env_values: dict[str, str | None] = {}
    for key, value in env.items():
        if value is not None and not isinstance(value, str):
            raise ArtifactRegistryError("command.env values must be strings or null")
        env_values[key] = value
    host_profile = manifest_entry.get("host_profile") or {}
    if not isinstance(host_profile, dict):
        raise ArtifactRegistryError("host_profile must be an object")
    source_directory = _required_relative_path(manifest_entry, "source_directory")
    agent_replay_summary = manifest_entry.get("agent_replay_summary")
    if agent_replay_summary is not None and not isinstance(agent_replay_summary, str):
        raise ArtifactRegistryError("agent_replay_summary must be a string when provided")
    if isinstance(agent_replay_summary, str) and _unsafe_retained_path(agent_replay_summary):
        raise ArtifactRegistryError("agent_replay_summary must be relative and cannot traverse parents")
    return build_registry_entry(
        root,
        registry_path=registry_path,
        artifact_dir=Path(source_directory),
        benchmark_set_id=str(manifest_entry.get("benchmark_set_id") or ""),
        command=shlex.join(argv),
        command_cwd=command.get("cwd") if isinstance(command.get("cwd"), str) else ".",
        run_id=str(manifest_entry.get("run_id") or ""),
        seed=manifest_entry.get("seed") if isinstance(manifest_entry.get("seed"), int) else None,
        env=env_values,
        host_profile=str(host_profile.get("profile_id") or "unknown"),
        docker_host_kind=host_profile.get("docker_host_kind") if isinstance(host_profile.get("docker_host_kind"), str) else None,
        docker_host=host_profile.get("docker_host") if isinstance(host_profile.get("docker_host"), str) else None,
        architecture=host_profile.get("architecture") if isinstance(host_profile.get("architecture"), str) else None,
        cpu_count=host_profile.get("cpu_count") if isinstance(host_profile.get("cpu_count"), int) else None,
        memory_bytes=host_profile.get("memory_bytes") if isinstance(host_profile.get("memory_bytes"), int) else None,
        docker_data_root_free_bytes=(
            host_profile.get("docker_data_root_free_bytes")
            if isinstance(host_profile.get("docker_data_root_free_bytes"), int)
            else None
        ),
        agent_replay_summary=Path(agent_replay_summary) if isinstance(agent_replay_summary, str) else None,
        created_at=created_at,
    )


def _required_relative_path(entry: dict[str, Any], field: str) -> str:
    value = entry.get(field)
    if not isinstance(value, str) or not value:
        raise ArtifactRegistryError(f"{field} must be a non-empty string")
    if _unsafe_retained_path(value):
        raise ArtifactRegistryError(f"{field} must be relative and cannot traverse parents")
    return value


def _validate_backfill_expectations(
    root: Path,
    manifest_path: Path,
    manifest_entry: dict[str, Any],
    candidate: dict[str, Any],
    entry_path: str,
) -> list[ArtifactRegistryFinding]:
    findings: list[ArtifactRegistryFinding] = []
    expected_state = manifest_entry.get("expected_state")
    if isinstance(expected_state, str) and candidate.get("state") != expected_state:
        findings.append(
            _registry_finding(
                manifest_path,
                f"{entry_path}.expected_state",
                "state",
                f"candidate state {candidate.get('state')} did not match expected {expected_state}",
            )
        )
    expected_failure_class = manifest_entry.get("expected_failure_class")
    if isinstance(expected_failure_class, str) and candidate.get("failure_class") != expected_failure_class:
        findings.append(
            _registry_finding(
                manifest_path,
                f"{entry_path}.expected_failure_class",
                "failure-class",
                f"candidate failure_class {candidate.get('failure_class')} did not match expected {expected_failure_class}",
            )
        )
    expected_item_count = manifest_entry.get("expected_item_count")
    replay = candidate.get("agent_replay")
    if isinstance(expected_item_count, int) and isinstance(replay, dict) and replay.get("count") != expected_item_count:
        findings.append(
            _registry_finding(
                manifest_path,
                f"{entry_path}.expected_item_count",
                "agent-replay-count",
                f"agent replay count {replay.get('count')} did not match expected {expected_item_count}",
            )
        )
    expected_case_run_ids = manifest_entry.get("expected_case_run_ids")
    if isinstance(expected_case_run_ids, list) and expected_case_run_ids:
        if not all(isinstance(item, str) and item for item in expected_case_run_ids):
            findings.append(
                _registry_finding(
                    manifest_path,
                    f"{entry_path}.expected_case_run_ids",
                    "type",
                    "expected_case_run_ids must be a string array",
                )
            )
        else:
            try:
                source_directory = _required_relative_path(manifest_entry, "source_directory")
                result = _load_required_json(root / source_directory / REQUIRED_ARTIFACTS["result_json"])
            except ArtifactRegistryError as exc:
                findings.append(
                    _registry_finding(
                        manifest_path,
                        f"{entry_path}.expected_case_run_ids",
                        "case-run-ids",
                        str(exc),
                    )
                )
            else:
                actual_case_run_ids = _case_run_ids(result)
                if actual_case_run_ids != expected_case_run_ids:
                    findings.append(
                        _registry_finding(
                            manifest_path,
                            f"{entry_path}.expected_case_run_ids",
                            "case-run-ids",
                            "expected_case_run_ids did not match source result run ids",
                        )
                    )
    return findings


def _case_run_ids(result: dict[str, Any]) -> list[str]:
    run_ids: list[str] = []
    for run in _runs(result):
        for key in ("incident_session_id", "incident_id"):
            value = run.get(key)
            if isinstance(value, str) and value:
                run_ids.append(value)
                break
    return run_ids


def _error_count(findings: list[ArtifactRegistryFinding]) -> int:
    return sum(1 for finding in findings if finding.severity == "error")


def _validate_registry_document(registry_path: Path, registry: dict[str, Any]) -> list[ArtifactRegistryFinding]:
    findings: list[ArtifactRegistryFinding] = []
    findings.extend(_missing_required_fields(registry_path, registry, REGISTRY_TOP_LEVEL_FIELDS, "$"))
    findings.extend(_unexpected_fields(registry_path, registry, REGISTRY_TOP_LEVEL_FIELDS, "$"))
    if registry.get("schema_version") != REGISTRY_SCHEMA_VERSION:
        findings.append(
            _registry_finding(
                registry_path,
                "$.schema_version",
                "schema-version",
                f"schema_version must be {REGISTRY_SCHEMA_VERSION}",
            )
        )
    findings.extend(_expect_nonempty_string(registry_path, registry, "created_at", "$.created_at"))
    if not isinstance(registry.get("entries"), list):
        findings.append(_registry_finding(registry_path, "$.entries", "type", "entries must be an array"))
    return findings


def _validate_registry_entry_document(
    root: Path,
    registry_path: Path,
    entry: dict[str, Any],
    json_path: str,
) -> list[ArtifactRegistryFinding]:
    findings: list[ArtifactRegistryFinding] = []
    findings.extend(_missing_required_fields(registry_path, entry, REGISTRY_ENTRY_REQUIRED_FIELDS, json_path))
    findings.extend(_unexpected_fields(registry_path, entry, REGISTRY_ENTRY_FIELDS, json_path))
    findings.extend(_expect_nonempty_string(registry_path, entry, "run_id", f"{json_path}.run_id"))
    findings.extend(_expect_nonempty_string(registry_path, entry, "benchmark_set_id", f"{json_path}.benchmark_set_id"))
    findings.extend(_expect_nullable_integer(registry_path, entry, "seed", f"{json_path}.seed"))
    findings.extend(_validate_scenario_ids(registry_path, entry, f"{json_path}.scenario_ids"))
    findings.extend(_expect_positive_integer(registry_path, entry, "combination_size", f"{json_path}.combination_size"))
    findings.extend(_expect_enum(registry_path, entry, "archetype", ARCHETYPES, f"{json_path}.archetype"))
    findings.extend(_expect_enum(registry_path, entry, "collection_mode", COLLECTION_MODES, f"{json_path}.collection_mode"))
    findings.extend(_expect_enum(registry_path, entry, "state", STATES, f"{json_path}.state"))
    findings.extend(_expect_enum(registry_path, entry, "failure_class", FAILURE_CLASSES, f"{json_path}.failure_class"))
    findings.extend(_expect_nonempty_string(registry_path, entry, "created_at", f"{json_path}.created_at"))
    findings.extend(_expect_object_or_null(registry_path, entry, "failure_classification", f"{json_path}.failure_classification"))
    findings.extend(_expect_object_or_null(registry_path, entry, "agent_replay", f"{json_path}.agent_replay"))
    if "notes" in entry and not isinstance(entry.get("notes"), str):
        findings.append(_registry_finding(registry_path, f"{json_path}.notes", "type", "notes must be a string"))
    findings.extend(_validate_host_profile_document(registry_path, entry.get("host_profile"), f"{json_path}.host_profile"))
    findings.extend(_validate_command_document(root, registry_path, entry.get("command"), f"{json_path}.command"))
    findings.extend(
        _validate_environment_fingerprint_document(
            registry_path,
            entry.get("environment_fingerprint"),
            f"{json_path}.environment_fingerprint",
        )
    )
    findings.extend(_validate_retained_paths_document(registry_path, entry.get("retained_paths"), f"{json_path}.retained_paths"))
    findings.extend(_validate_content_hashes_document(registry_path, entry.get("content_hashes"), f"{json_path}.content_hashes"))
    return findings


def _validate_host_profile_document(
    registry_path: Path,
    value: Any,
    json_path: str,
) -> list[ArtifactRegistryFinding]:
    if not isinstance(value, dict):
        return [_registry_finding(registry_path, json_path, "type", "host_profile must be an object")]
    findings: list[ArtifactRegistryFinding] = []
    findings.extend(_missing_required_fields(registry_path, value, HOST_PROFILE_REQUIRED_FIELDS, json_path))
    findings.extend(_unexpected_fields(registry_path, value, HOST_PROFILE_FIELDS, json_path))
    findings.extend(_expect_nonempty_string(registry_path, value, "profile_id", f"{json_path}.profile_id"))
    findings.extend(_expect_enum(registry_path, value, "docker_host_kind", DOCKER_HOST_KINDS, f"{json_path}.docker_host_kind"))
    findings.extend(_expect_nullable_string(registry_path, value, "docker_host", f"{json_path}.docker_host"))
    findings.extend(_expect_nullable_string(registry_path, value, "architecture", f"{json_path}.architecture"))
    findings.extend(_expect_nullable_positive_integer(registry_path, value, "cpu_count", f"{json_path}.cpu_count"))
    findings.extend(_expect_nullable_positive_integer(registry_path, value, "memory_bytes", f"{json_path}.memory_bytes"))
    findings.extend(
        _expect_nullable_nonnegative_integer(
            registry_path,
            value,
            "docker_data_root_free_bytes",
            f"{json_path}.docker_data_root_free_bytes",
        )
    )
    return findings


def _validate_command_document(
    root: Path,
    registry_path: Path,
    value: Any,
    json_path: str,
) -> list[ArtifactRegistryFinding]:
    if not isinstance(value, dict):
        return [_registry_finding(registry_path, json_path, "type", "command must be an object")]
    findings: list[ArtifactRegistryFinding] = []
    findings.extend(_missing_required_fields(registry_path, value, COMMAND_REQUIRED_FIELDS, json_path))
    findings.extend(_unexpected_fields(registry_path, value, COMMAND_FIELDS, json_path))
    argv = value.get("argv")
    if not isinstance(argv, list) or not argv:
        findings.append(_registry_finding(registry_path, f"{json_path}.argv", "type", "argv must be a non-empty array"))
    elif not all(isinstance(item, str) for item in argv):
        findings.append(_registry_finding(registry_path, f"{json_path}.argv", "type", "argv items must be strings"))
    findings.extend(_expect_nullable_string(registry_path, value, "cwd", f"{json_path}.cwd"))
    env = value.get("env", {})
    if env is None:
        return findings
    if not isinstance(env, dict):
        findings.append(_registry_finding(registry_path, f"{json_path}.env", "type", "env must be an object"))
        return findings
    home = str(Path.home())
    for key, env_value in sorted(env.items()):
        key_path = f"{json_path}.env.{key}"
        if not isinstance(key, str):
            findings.append(_registry_finding(registry_path, f"{json_path}.env", "type", "env keys must be strings"))
            continue
        if env_value is not None and not isinstance(env_value, str):
            findings.append(_registry_finding(registry_path, key_path, "type", "env values must be strings or null"))
            continue
        if SENSITIVE_ENV_PATTERN.search(key) and env_value is not None and env_value.lower() != "[redacted]":
            findings.append(_registry_finding(registry_path, key_path, "unredacted-env", f"{key} must be redacted"))
        if isinstance(env_value, str) and home and home in env_value:
            findings.append(
                _registry_finding(
                    registry_path,
                    key_path,
                    "unsafe-env",
                    f"{key} contains an unredacted local home directory path",
                )
            )
        if isinstance(env_value, str) and str(root) in env_value:
            findings.append(
                _registry_finding(
                    registry_path,
                    key_path,
                    "unsafe-env",
                    f"{key} contains an unredacted repository path",
                )
            )
    return findings


def _validate_environment_fingerprint_document(
    registry_path: Path,
    value: Any,
    json_path: str,
) -> list[ArtifactRegistryFinding]:
    if not isinstance(value, dict):
        return [_registry_finding(registry_path, json_path, "type", "environment_fingerprint must be an object")]
    findings: list[ArtifactRegistryFinding] = []
    findings.extend(_missing_required_fields(registry_path, value, ENVIRONMENT_FINGERPRINT_REQUIRED_FIELDS, json_path))
    findings.extend(_expect_nonempty_string(registry_path, value, "fingerprint_id", f"{json_path}.fingerprint_id"))
    for key in (
        "docker_server_version",
        "docker_architecture",
        "kind_node_image",
        "cluster_name",
        "compose_project",
    ):
        findings.extend(_expect_nullable_string(registry_path, value, key, f"{json_path}.{key}"))
    for key in ("warm_kind", "observability_reuse_ready"):
        if key in value and value.get(key) is not None and not isinstance(value.get(key), bool):
            findings.append(_registry_finding(registry_path, f"{json_path}.{key}", "type", f"{key} must be boolean or null"))
    timeout_overrides = value.get("timeout_overrides", {})
    if timeout_overrides is not None and not isinstance(timeout_overrides, dict):
        findings.append(
            _registry_finding(
                registry_path,
                f"{json_path}.timeout_overrides",
                "type",
                "timeout_overrides must be an object",
            )
        )
    elif isinstance(timeout_overrides, dict):
        for key, timeout_value in sorted(timeout_overrides.items()):
            if not isinstance(key, str) or not isinstance(timeout_value, str):
                findings.append(
                    _registry_finding(
                        registry_path,
                        f"{json_path}.timeout_overrides",
                        "type",
                        "timeout override keys and values must be strings",
                    )
                )
                break
    image_cache = value.get("image_cache", {})
    if image_cache is not None and not isinstance(image_cache, dict):
        findings.append(_registry_finding(registry_path, f"{json_path}.image_cache", "type", "image_cache must be an object"))
    return findings


def _validate_retained_paths_document(
    registry_path: Path,
    value: Any,
    json_path: str,
) -> list[ArtifactRegistryFinding]:
    if not isinstance(value, dict):
        return [_registry_finding(registry_path, json_path, "type", "retained_paths must be an object")]
    findings: list[ArtifactRegistryFinding] = []
    findings.extend(_missing_required_fields(registry_path, value, RETAINED_PATH_REQUIRED_FIELDS, json_path))
    for key, retained_path in sorted(value.items()):
        field_path = f"{json_path}.{key}"
        if not isinstance(key, str):
            findings.append(_registry_finding(registry_path, json_path, "type", "retained path keys must be strings"))
        if not isinstance(retained_path, str) or not retained_path:
            findings.append(_registry_finding(registry_path, field_path, "type", "retained paths must be non-empty strings"))
            continue
        if _unsafe_retained_path(retained_path):
            findings.append(
                _registry_finding(
                    registry_path,
                    field_path,
                    "unsafe-path",
                    "retained paths must be relative paths without parent traversal",
                )
            )
    return findings


def _validate_content_hashes_document(
    registry_path: Path,
    value: Any,
    json_path: str,
) -> list[ArtifactRegistryFinding]:
    if not isinstance(value, dict):
        return [_registry_finding(registry_path, json_path, "type", "content_hashes must be an object")]
    findings: list[ArtifactRegistryFinding] = []
    findings.extend(_missing_required_fields(registry_path, value, RETAINED_PATH_REQUIRED_FIELDS, json_path))
    for key, content_hash in sorted(value.items()):
        field_path = f"{json_path}.{key}"
        if not isinstance(key, str):
            findings.append(_registry_finding(registry_path, json_path, "type", "content hash keys must be strings"))
        if not isinstance(content_hash, dict):
            findings.append(_registry_finding(registry_path, field_path, "type", "content hash must be an object"))
            continue
        findings.extend(_missing_required_fields(registry_path, content_hash, CONTENT_HASH_REQUIRED_FIELDS, field_path))
        findings.extend(_unexpected_fields(registry_path, content_hash, CONTENT_HASH_REQUIRED_FIELDS, field_path))
        if content_hash.get("algorithm") != HASH_ALGORITHM:
            findings.append(_registry_finding(registry_path, f"{field_path}.algorithm", "content-hash", "algorithm must be sha256"))
        value_field = content_hash.get("value")
        if not isinstance(value_field, str) or not HASH_VALUE_PATTERN.fullmatch(value_field):
            findings.append(
                _registry_finding(
                    registry_path,
                    f"{field_path}.value",
                    "content-hash",
                    "hash value must be 64 lowercase hex characters",
                )
            )
    return findings


def _validate_retained_artifacts(
    root: Path,
    registry_path: Path,
    entry: dict[str, Any],
    json_path: str,
) -> list[ArtifactRegistryFinding]:
    findings: list[ArtifactRegistryFinding] = []
    retained_paths = entry.get("retained_paths")
    content_hashes = entry.get("content_hashes")
    if not isinstance(retained_paths, dict) or not isinstance(content_hashes, dict):
        return findings
    for key in sorted(retained_paths):
        if key not in content_hashes:
            findings.append(
                _registry_finding(
                    registry_path,
                    f"{json_path}.content_hashes.{key}",
                    "content-hash",
                    f"content_hashes is missing retained path key {key}",
                )
            )
    for key in sorted(content_hashes):
        if key not in retained_paths:
            findings.append(
                _registry_finding(
                    registry_path,
                    f"{json_path}.retained_paths.{key}",
                    "retained-path",
                    f"retained_paths is missing content hash key {key}",
                )
            )

    result_payload: dict[str, Any] | None = None
    for key, retained_path in sorted(retained_paths.items()):
        if not isinstance(retained_path, str) or not retained_path or _unsafe_retained_path(retained_path):
            continue
        path = _resolve_retained_path(root, registry_path, retained_path)
        if not path.is_file():
            findings.append(
                _registry_finding(
                    registry_path,
                    f"{json_path}.retained_paths.{key}",
                    "artifact-missing",
                    f"retained artifact is missing: {retained_path}",
                )
            )
            continue
        expected_hash = content_hashes.get(key)
        if isinstance(expected_hash, dict) and expected_hash.get("algorithm") == HASH_ALGORITHM:
            expected_value = expected_hash.get("value")
            if isinstance(expected_value, str) and HASH_VALUE_PATTERN.fullmatch(expected_value):
                actual_value = _sha256_file(path)
                if actual_value != expected_value:
                    findings.append(
                        _registry_finding(
                            registry_path,
                            f"{json_path}.content_hashes.{key}.value",
                            "artifact-hash",
                            f"retained artifact hash drifted for {retained_path}",
                        )
                    )
        if key == "result_json":
            try:
                result_payload = _load_json_document(path, label="result_json")
            except ArtifactRegistryError as exc:
                findings.append(_registry_finding(registry_path, f"{json_path}.retained_paths.{key}", "artifact-json", str(exc)))
    findings.extend(_validate_combination_size(registry_path, entry, json_path, result_payload))
    return findings


def _validate_combination_size(
    registry_path: Path,
    entry: dict[str, Any],
    json_path: str,
    result_payload: dict[str, Any] | None,
) -> list[ArtifactRegistryFinding]:
    scenario_ids = entry.get("scenario_ids")
    combination_size = entry.get("combination_size")
    if not isinstance(scenario_ids, list) or not _is_int(combination_size):
        return []
    if not all(isinstance(item, str) for item in scenario_ids):
        return []
    if not _enforce_single_run_combination_size(result_payload):
        return []
    if int(combination_size) == len(scenario_ids):
        return []
    return [
        _registry_finding(
            registry_path,
            f"{json_path}.combination_size",
            "cross-field",
            "combination_size must match scenario_ids length for single-run registry entries",
        )
    ]


def _enforce_single_run_combination_size(result_payload: dict[str, Any] | None) -> bool:
    if result_payload is None:
        return True
    if result_payload.get("batch"):
        count = result_payload.get("count")
        if _is_int(count) and int(count) > 1:
            return False
        runs = result_payload.get("runs")
        if isinstance(runs, list) and len(runs) > 1:
            return False
    return True


def _resolve_retained_path(root: Path, registry_path: Path, retained_path: str) -> Path:
    root_candidate = root / retained_path
    if root_candidate.is_file():
        return root_candidate
    return registry_path.parent / retained_path


def _unsafe_retained_path(value: str) -> bool:
    if Path(value).is_absolute() or value.startswith("~"):
        return True
    parts = PurePosixPath(value).parts
    return ".." in parts


def _validate_scenario_ids(
    registry_path: Path,
    entry: dict[str, Any],
    json_path: str,
) -> list[ArtifactRegistryFinding]:
    value = entry.get("scenario_ids")
    if not isinstance(value, list) or not value:
        return [_registry_finding(registry_path, json_path, "type", "scenario_ids must be a non-empty array")]
    findings: list[ArtifactRegistryFinding] = []
    seen: set[str] = set()
    for index, item in enumerate(value):
        item_path = f"{json_path}[{index}]"
        if not isinstance(item, str) or not item:
            findings.append(_registry_finding(registry_path, item_path, "type", "scenario_ids items must be non-empty strings"))
            continue
        if item in seen:
            findings.append(_registry_finding(registry_path, item_path, "duplicate-scenario-id", f"duplicate scenario id: {item}"))
        seen.add(item)
    return findings


def _missing_required_fields(
    registry_path: Path,
    value: dict[str, Any],
    required: set[str],
    json_path: str,
) -> list[ArtifactRegistryFinding]:
    return [
        _registry_finding(registry_path, f"{json_path}.{field}", "required-field", f"missing required field: {field}")
        for field in sorted(required)
        if field not in value
    ]


def _unexpected_fields(
    registry_path: Path,
    value: dict[str, Any],
    allowed: set[str],
    json_path: str,
) -> list[ArtifactRegistryFinding]:
    return [
        _registry_finding(registry_path, f"{json_path}.{field}", "unexpected-field", f"unexpected field: {field}")
        for field in sorted(value)
        if field not in allowed
    ]


def _expect_nonempty_string(
    registry_path: Path,
    value: dict[str, Any],
    field: str,
    json_path: str,
) -> list[ArtifactRegistryFinding]:
    if field not in value:
        return []
    if isinstance(value.get(field), str) and value.get(field):
        return []
    return [_registry_finding(registry_path, json_path, "type", f"{field} must be a non-empty string")]


def _expect_nullable_string(
    registry_path: Path,
    value: dict[str, Any],
    field: str,
    json_path: str,
) -> list[ArtifactRegistryFinding]:
    if field not in value or value.get(field) is None or isinstance(value.get(field), str):
        return []
    return [_registry_finding(registry_path, json_path, "type", f"{field} must be a string or null")]


def _expect_nullable_integer(
    registry_path: Path,
    value: dict[str, Any],
    field: str,
    json_path: str,
) -> list[ArtifactRegistryFinding]:
    if field not in value or value.get(field) is None or _is_int(value.get(field)):
        return []
    return [_registry_finding(registry_path, json_path, "type", f"{field} must be an integer or null")]


def _expect_positive_integer(
    registry_path: Path,
    value: dict[str, Any],
    field: str,
    json_path: str,
) -> list[ArtifactRegistryFinding]:
    if field not in value:
        return []
    if _is_int(value.get(field)) and int(value[field]) >= 1:
        return []
    return [_registry_finding(registry_path, json_path, "type", f"{field} must be a positive integer")]


def _expect_nullable_positive_integer(
    registry_path: Path,
    value: dict[str, Any],
    field: str,
    json_path: str,
) -> list[ArtifactRegistryFinding]:
    if field not in value or value.get(field) is None:
        return []
    if _is_int(value.get(field)) and int(value[field]) >= 1:
        return []
    return [_registry_finding(registry_path, json_path, "type", f"{field} must be a positive integer or null")]


def _expect_nullable_nonnegative_integer(
    registry_path: Path,
    value: dict[str, Any],
    field: str,
    json_path: str,
) -> list[ArtifactRegistryFinding]:
    if field not in value or value.get(field) is None:
        return []
    if _is_int(value.get(field)) and int(value[field]) >= 0:
        return []
    return [_registry_finding(registry_path, json_path, "type", f"{field} must be a non-negative integer or null")]


def _expect_enum(
    registry_path: Path,
    value: dict[str, Any],
    field: str,
    allowed: set[str],
    json_path: str,
) -> list[ArtifactRegistryFinding]:
    if field not in value:
        return []
    if isinstance(value.get(field), str) and value.get(field) in allowed:
        return []
    return [
        _registry_finding(
            registry_path,
            json_path,
            "enum",
            f"{field} must be one of: {', '.join(sorted(allowed))}",
        )
    ]


def _expect_object_or_null(
    registry_path: Path,
    value: dict[str, Any],
    field: str,
    json_path: str,
) -> list[ArtifactRegistryFinding]:
    if field not in value or value.get(field) is None or isinstance(value.get(field), dict):
        return []
    return [_registry_finding(registry_path, json_path, "type", f"{field} must be an object or null")]


def _registry_finding(
    registry_path: Path,
    json_path: str,
    rule: str,
    message: str,
    *,
    severity: str = "error",
) -> ArtifactRegistryFinding:
    return ArtifactRegistryFinding(
        severity=severity,
        rule=rule,
        path=str(registry_path),
        json_path=json_path,
        message=message,
    )


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _markdown_entry_row(entry: dict[str, Any]) -> str:
    scenarios = entry.get("scenario_ids")
    retained_paths = entry.get("retained_paths")
    mode = "/".join(
        item
        for item in (str(entry.get("archetype", "")), str(entry.get("collection_mode", "")))
        if item
    )
    host_profile = entry.get("host_profile") if isinstance(entry.get("host_profile"), dict) else {}
    host = str(host_profile.get("profile_id", "unknown"))
    if host_profile.get("docker_host_kind"):
        host = f"{host} ({host_profile['docker_host_kind']})"
    return "| {run_id} | {benchmark_set_id} | {seed} | {scenarios} | {size} | {mode} | {host} | {state} | {failure_class} | {artifact_count} |".format(
        run_id=_markdown_escape(str(entry.get("run_id", ""))),
        benchmark_set_id=_markdown_escape(str(entry.get("benchmark_set_id", ""))),
        seed=_markdown_escape("" if entry.get("seed") is None else str(entry.get("seed"))),
        scenarios=_markdown_escape(", ".join(scenarios) if isinstance(scenarios, list) else ""),
        size=_markdown_escape(str(entry.get("combination_size", ""))),
        mode=_markdown_escape(mode),
        host=_markdown_escape(host),
        state=_markdown_escape(str(entry.get("state", ""))),
        failure_class=_markdown_escape(str(entry.get("failure_class", ""))),
        artifact_count=len(retained_paths) if isinstance(retained_paths, dict) else 0,
    )


def _markdown_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def _redact_env_value(key: str, value: str | None) -> str | None:
    if value is None:
        return None
    if SENSITIVE_ENV_PATTERN.search(key):
        return "[redacted]"
    home = str(Path.home())
    if home and home in value:
        return value.replace(home, "${HOME}")
    return value


def _docker_host_from_env_or_result(env: dict[str, str | None], result: dict[str, Any]) -> str | None:
    value = env.get("DOCKER_HOST") or os.environ.get("DOCKER_HOST")
    if value:
        return str(value)
    runtime_values = _runtime_values(result)
    for runtime in runtime_values:
        docker_host = runtime.get("docker_host")
        if docker_host:
            return str(docker_host)
    return None


def _docker_host_kind(collection_mode: str, docker_host_kind: str | None, docker_host: str | None) -> str:
    if docker_host_kind:
        if docker_host_kind not in DOCKER_HOST_KINDS:
            raise ArtifactRegistryError(f"unsupported docker_host_kind: {docker_host_kind}")
        return docker_host_kind
    if collection_mode == "fixture":
        return "none"
    if docker_host and docker_host.startswith("ssh://"):
        return "ssh"
    if docker_host:
        return "local"
    return "unknown"


def _runtime_values(result: dict[str, Any]) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    for run in _runs(result):
        context = run.get("context") if isinstance(run, dict) else None
        if isinstance(context, dict):
            runtime = context.get("runtime_state")
            if isinstance(runtime, dict):
                values.append(runtime)
            for key in ("archetype", "cluster", "compose_project", "kubeconfig_path"):
                if key in context:
                    values.append(context)
                    break
    return values


def _environment_fingerprint(
    result: dict[str, Any],
    *,
    redacted_env: dict[str, str | None],
    docker_host: str | None,
    architecture: str | None,
) -> dict[str, Any]:
    timeout_overrides = {key: value for key, value in redacted_env.items() if key in TIMEOUT_ENV_KEYS}
    cluster_name, compose_project = _cluster_and_compose(result)
    warm_kind = _warm_kind_enabled(result)
    fingerprint = {
        "docker_server_version": None,
        "docker_architecture": architecture,
        "kind_node_image": "kindest/node" if _archetype(result) == "kind" else None,
        "cluster_name": cluster_name,
        "compose_project": compose_project,
        "warm_kind": warm_kind,
        "observability_reuse_ready": _observability_reuse_ready(result),
        "timeout_overrides": timeout_overrides,
        "image_cache": {
            "docker_host": docker_host,
            "local_harness_images": "unknown",
        },
    }
    fingerprint["fingerprint_id"] = "sha256:" + _sha256_text(_canonical_json(fingerprint))
    return fingerprint


def _cluster_and_compose(result: dict[str, Any]) -> tuple[str | None, str | None]:
    cluster = None
    compose = None
    for runtime in _runtime_values(result):
        cluster = cluster or runtime.get("cluster")
        compose = compose or runtime.get("compose_project")
    if cluster is None:
        warm_kind = result.get("warm_kind") if isinstance(result.get("warm_kind"), dict) else None
        if isinstance(warm_kind, dict):
            cleanup = warm_kind.get("cleanup")
            if isinstance(cleanup, dict):
                cluster = cleanup.get("cluster")
    return cluster, compose


def _warm_kind_enabled(result: dict[str, Any]) -> bool | None:
    warm_kind = result.get("warm_kind")
    if isinstance(warm_kind, dict):
        return bool(warm_kind.get("enabled"))
    for runtime in _runtime_values(result):
        if "keep_cluster" in runtime:
            return bool(runtime.get("keep_cluster"))
    return None


def _observability_reuse_ready(result: dict[str, Any]) -> bool | None:
    for runtime in _runtime_values(result):
        if "observability_reuse_ready" in runtime:
            return bool(runtime.get("observability_reuse_ready"))
    return None


def _runs(result: dict[str, Any]) -> list[dict[str, Any]]:
    runs = result.get("runs")
    if result.get("batch") and isinstance(runs, list):
        return [run for run in runs if isinstance(run, dict)]
    return [result]


def _scenario_ids(result: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for run in _runs(result):
        scenarios = run.get("scenarios")
        if isinstance(scenarios, list):
            for scenario in scenarios:
                if isinstance(scenario, dict) and scenario.get("name"):
                    names.append(str(scenario["name"]))
            continue
        if run.get("scenario"):
            names.append(str(run["scenario"]))
    unique: list[str] = []
    seen: set[str] = set()
    for name in names:
        if name not in seen:
            seen.add(name)
            unique.append(name)
    return unique or ["unknown"]


def _combination_size(result: dict[str, Any], scenario_ids: list[str]) -> int:
    sizes = {
        int(run["scenario_count"])
        for run in _runs(result)
        if isinstance(run.get("scenario_count"), int) and int(run["scenario_count"]) > 0
    }
    if len(sizes) == 1:
        return next(iter(sizes))
    source = result.get("combination_source")
    if isinstance(source, dict) and isinstance(source.get("random_combination_size"), int):
        return int(source["random_combination_size"])
    return max(1, len(scenario_ids))


def _collection_mode(result: dict[str, Any]) -> str:
    value = result.get("collection_mode")
    if isinstance(value, str) and value in COLLECTION_MODES:
        return value
    for run in _runs(result):
        value = run.get("collection_mode")
        if isinstance(value, str) and value in COLLECTION_MODES:
            return value
    return "fixture"


def _archetype(result: dict[str, Any]) -> str:
    values = {
        str(run.get("environment_archetype"))
        for run in _runs(result)
        if run.get("environment_archetype")
    }
    if not values and result.get("environment_archetype"):
        values.add(str(result["environment_archetype"]))
    normalized = {value if value in ARCHETYPES else "unknown" for value in values}
    if not normalized:
        return "fixture" if _collection_mode(result) == "fixture" else "unknown"
    if len(normalized) == 1:
        return next(iter(normalized))
    return "mixed"


def _result_seed(result: dict[str, Any]) -> int | None:
    source = result.get("combination_source")
    if isinstance(source, dict) and isinstance(source.get("random_seed"), int):
        return int(source["random_seed"])
    return None


def _state(result: dict[str, Any], replay: dict[str, Any] | None) -> str:
    if replay is not None and replay.get("passed") is False:
        return "failed"
    if replay is not None and replay.get("passed") is True and result.get("generated") is True and not result.get("blocked"):
        return "passed"
    if result.get("batch") and result.get("generated_count") and result.get("blocked_count"):
        return "partial"
    if result.get("blocked") is True:
        return "blocked"
    if result.get("generated") is True:
        return "generated"
    return "failed"


def _failure_class(result: dict[str, Any], replay: dict[str, Any] | None) -> str:
    if replay is not None and replay.get("passed") is False:
        return "agent_hypothesis_regression"
    value = result.get("failure_class")
    if isinstance(value, str) and value in FAILURE_CLASSES:
        return value
    if result.get("blocked"):
        return "validation_issue"
    return "none"


def _agent_replay_summary(replay: dict[str, Any] | None) -> dict[str, Any] | None:
    if replay is None:
        return None
    summary: dict[str, Any] = {}
    for key in ("schema_version", "agent", "llm_model", "synthesized", "count", "passed_count", "passed", "duration_ms"):
        if key in replay:
            summary[key] = replay[key]
    return summary


def _default_run_id(artifact_dir: Path, result: dict[str, Any]) -> str:
    session = result.get("incident_session_id")
    if isinstance(session, str) and session:
        return _slug(session)
    return _slug(artifact_dir.name)


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", value.strip()).strip("-._")
    return slug or "incident-generator-run"


def _validate_entry(entry: dict[str, Any]) -> None:
    if entry["failure_class"] not in FAILURE_CLASSES:
        raise ArtifactRegistryError(f"unsupported failure_class: {entry['failure_class']}")
    if entry["state"] not in STATES:
        raise ArtifactRegistryError(f"unsupported state: {entry['state']}")
    if entry["archetype"] not in ARCHETYPES:
        raise ArtifactRegistryError(f"unsupported archetype: {entry['archetype']}")
    if entry["collection_mode"] not in COLLECTION_MODES:
        raise ArtifactRegistryError(f"unsupported collection_mode: {entry['collection_mode']}")
    if entry["host_profile"]["docker_host_kind"] not in DOCKER_HOST_KINDS:
        raise ArtifactRegistryError(f"unsupported docker_host_kind: {entry['host_profile']['docker_host_kind']}")
    if entry["combination_size"] < 1:
        raise ArtifactRegistryError("combination_size must be positive")
