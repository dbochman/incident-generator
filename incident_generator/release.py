"""Release manifest generation for incident-generator artifacts."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .scenarios import build_catalog_report, list_scenario_packages, load_scenario_package


MANIFEST_API_VERSION = "incident-generator-release/v1alpha1"
SCENARIO_SCHEMA_VERSION = "sre-agent-scenario/v1alpha1"
BENCHMARK_RELEASE_SCHEMA_VERSION = "incident-generator.benchmark-release/v1"

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
        "benchmark_set_id": "benchmark-combo-llm-smoke-20260506",
        "mode": "fixture LLM smoke plus Tier 2 judge wiring",
        "collection_modes": ["fixture"],
        "item_kind": "pair",
        "size": 4,
        "seed": 20260506,
        "status": "complete_with_blocked_live_provider",
        "host_profiles": [],
        "source_paths": ["harness/benchmark-combo-llm-smoke.yaml"],
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


def _benchmark_release(root: Path, catalog: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": BENCHMARK_RELEASE_SCHEMA_VERSION,
        "hash_algorithm": "sha256",
        "scenario_hashes": _scenario_hashes(root, catalog),
        "benchmark_sets": _benchmark_sets(root),
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
        "The benchmark result schema is published, but no standalone runner command emits result payloads directly yet.",
        "Live LLM benchmark execution is blocked until model credentials and separate-family judge settings are provided.",
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
