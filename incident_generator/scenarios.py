"""Scenario catalog loading and incident environment lifecycle helpers."""

from __future__ import annotations

import copy
import os
import re
import shutil
import subprocess
import tempfile
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from .parsers import load_yaml
from .provider_contracts import (
    ProviderProfile,
    default_provider_contracts,
    provider_profile,
    resolve_environment,
    rewrite_endpoints_for_local_ports,
)
from .scenario_runtime import SeedExecutor, SymptomWaiter, default_predicates, resolve_selectors, start_port_forwards


COLLECTION_MODES = {"fixture", "real"}
FALLBACK_ARCHETYPES = {"kind", "linux-vm"}
ARCHETYPE_PROFILES: dict[str, str | None] = {
    "fixture": None,
    "kind": "harness-local",
    "linux-vm": "harness-local-linux-vm",
    "eks-staging": "harness-local",
    "multirepo-sandbox": None,
}

ToolLookup = Callable[[str], Optional[str]]
SubprocessBoundary = Callable[..., subprocess.CompletedProcess]


def _noop_teardown() -> None:
    return None


@dataclass(frozen=True)
class ScenarioPackage:
    path: Path
    spec: dict[str, Any]
    expect: dict[str, Any]

    @property
    def name(self) -> str:
        metadata = self.spec.get("metadata", {})
        return str(metadata.get("name") or self.path.name)

    @property
    def domain(self) -> str:
        metadata = self.spec.get("metadata", {})
        return str(metadata.get("domain") or "")

    @property
    def skill_path(self) -> Path:
        return _resolve_path(self.path, str(self.spec.get("skill_under_test", "")))

    @property
    def fixture_path(self) -> Path:
        return _resolve_path(self.path, str(self.spec.get("fixture", "")))

    @property
    def seed_path(self) -> Path:
        return self.path / "seed"

    @property
    def wait_for(self) -> dict[str, Any]:
        value = self.expect.get("wait_for", {})
        return copy.deepcopy(value) if isinstance(value, dict) else {}

    @property
    def cross_incident(self) -> dict[str, Any]:
        value = self.spec.get("cross_incident", {})
        return copy.deepcopy(value) if isinstance(value, dict) else {}


@dataclass
class ArchetypeContext:
    archetype: str
    host_env: dict[str, str]
    provider_profile: ProviderProfile | None = None
    teardown: Callable[[], None] = _noop_teardown
    kubeconfig_path: str | None = None
    compose_project: str | None = None
    precondition_failures: list[dict[str, str]] = field(default_factory=list)


def list_scenario_packages(root: Path) -> list[Path]:
    scenario_root = root / "scenarios"
    return sorted(path.parent for path in scenario_root.glob("**/scenario.yaml"))


def load_scenario_package(path: Path) -> ScenarioPackage:
    root = path if path.is_dir() else path.parent
    spec_path = root / "scenario.yaml" if path.is_dir() else path
    spec = load_yaml(spec_path)
    expect_path = root / "expect.yaml"
    expect = load_yaml(expect_path) if expect_path.exists() else {}
    return ScenarioPackage(path=root, spec=spec, expect=expect)


def build_catalog_report(root: Path) -> dict[str, Any]:
    packages = [load_scenario_package(path) for path in list_scenario_packages(root)]
    rows = [_catalog_row(root, package) for package in packages]
    return {
        "count": len(rows),
        "by_domain": _counter_dict(row["domain"] for row in rows),
        "by_archetype": _counter_dict(row["environment_archetype"] for row in rows),
        "by_live_readiness": _counter_dict(row["live_readiness"] for row in rows),
        "by_evidence_adapter": _counter_dict(adapter for row in rows for adapter in row["evidence_adapters_required"]),
        "domains": {
            domain: {
                "count": len(domain_rows),
                "live_readiness": _counter_dict(row["live_readiness"] for row in domain_rows),
                "archetypes": _counter_dict(row["environment_archetype"] for row in domain_rows),
            }
            for domain, domain_rows in _group_rows(rows, "domain").items()
        },
        "scenarios": rows,
    }


def profile_for_archetype(archetype: str) -> ProviderProfile | None:
    if archetype == "multirepo-sandbox":
        raise ValueError("multirepo-sandbox archetype is reserved and not supported by this runner")
    if archetype not in ARCHETYPE_PROFILES:
        raise ValueError(f"unknown environment_archetype: {archetype!r}")
    profile_name = ARCHETYPE_PROFILES[archetype]
    return provider_profile(profile_name) if profile_name is not None else None


def dispatch_archetype(
    archetype: str,
    *,
    package: ScenarioPackage,
    workdir: Path,
    host_env: Mapping[str, str] | None = None,
    tool_lookup: ToolLookup = shutil.which,
    command_runner: SubprocessBoundary | None = None,
) -> ArchetypeContext:
    base_env = dict(host_env or os.environ)
    command_runner = command_runner or _run_subprocess
    profile = profile_for_archetype(archetype)
    if archetype == "fixture":
        return ArchetypeContext(archetype=archetype, host_env=base_env, provider_profile=profile)
    if archetype == "kind":
        return _dispatch_kind(
            workdir=workdir,
            host_env=base_env,
            provider_profile=profile,
            tool_lookup=tool_lookup,
            command_runner=command_runner,
        )
    if archetype == "linux-vm":
        return _dispatch_linux_vm(
            package=package,
            workdir=workdir,
            host_env=base_env,
            provider_profile=profile,
            tool_lookup=tool_lookup,
            command_runner=command_runner,
        )
    if archetype == "eks-staging":
        return ArchetypeContext(
            archetype=archetype,
            host_env=base_env,
            provider_profile=profile,
            precondition_failures=[
                {"check": "eks-staging", "error": "eks-staging archetype dispatch is not implemented yet"}
            ],
        )
    raise ValueError(f"unknown environment_archetype: {archetype!r}")


def validate_scenario_package(package: ScenarioPackage, *, require_benchmark_assets: bool = True) -> list[str]:
    failures: list[str] = []
    spec = package.spec
    failures.extend(_validate_scenario_contract(package))
    if spec.get("apiVersion") != "sre-agent-scenario/v1alpha1":
        failures.append("apiVersion must be sre-agent-scenario/v1alpha1")
    if spec.get("kind") != "ScenarioPackage":
        failures.append("kind must be ScenarioPackage")
    metadata = spec.get("metadata", {})
    if not isinstance(metadata, dict) or not metadata.get("name"):
        failures.append("metadata.name is required")
    for field_name in [
        "skill_under_test",
        "fixture",
        "environment_archetype",
        "inputs",
        "evidence_adapters_required",
        "expected_hypotheses",
        "expected_action_templates",
        "forbidden_actions",
        "success_criteria",
        "latency_budget_ms",
        "variant_axes",
    ]:
        if field_name not in spec:
            failures.append(f"{field_name} is required")
    if require_benchmark_assets:
        if not package.skill_path.is_file():
            failures.append(f"skill_under_test does not exist: {package.skill_path}")
        if not package.fixture_path.is_dir():
            failures.append(f"fixture does not exist: {package.fixture_path}")
        if not (package.fixture_path / "fixture.yaml").is_file():
            failures.append(f"fixture.yaml is missing in {package.fixture_path}")
        if not (package.fixture_path / "outputs").is_dir():
            failures.append(f"outputs directory is missing in {package.fixture_path}")
    if not (package.path / "expect.yaml").is_file():
        failures.append("expect.yaml is required")
    for dirname in ("infra", "seed"):
        if not (package.path / dirname).is_dir():
            failures.append(f"{dirname}/ directory is required")
    for script in ("inject.sh", "cleanup.sh"):
        script_path = package.path / script
        if not script_path.is_file():
            failures.append(f"{script} is required")
        elif not script_path.stat().st_mode & 0o111:
            failures.append(f"{script} must be executable")
    variant_axes = spec.get("variant_axes", {})
    if not isinstance(variant_axes, dict):
        failures.append("variant_axes must be a mapping")
    else:
        for axis, values in variant_axes.items():
            if not isinstance(values, list) or not values:
                failures.append(f"variant_axes.{axis} must be a non-empty list")
    failures.extend(_validate_expect_contract(package))
    if require_benchmark_assets:
        failures.extend(_validate_fixture_output_references(package))
    return failures


def _validate_scenario_contract(package: ScenarioPackage) -> list[str]:
    failures: list[str] = []
    spec = package.spec
    if not isinstance(spec, dict):
        return ["scenario.yaml must be a mapping"]
    required_types: dict[str, type | tuple[type, ...]] = {
        "apiVersion": str,
        "kind": str,
        "metadata": dict,
        "skill_under_test": str,
        "fixture": str,
        "environment_archetype": str,
        "inputs": dict,
        "evidence_adapters_required": list,
        "expected_hypotheses": list,
        "expected_action_templates": list,
        "forbidden_actions": list,
        "success_criteria": dict,
        "latency_budget_ms": int,
        "variant_axes": dict,
    }
    for field_name, expected_type in required_types.items():
        if field_name in spec and not isinstance(spec[field_name], expected_type):
            failures.append(f"{field_name} must be {_type_name(expected_type)}")
    metadata = spec.get("metadata", {})
    if isinstance(metadata, dict):
        for field_name in ("name", "domain", "symptom", "variant", "owner"):
            if not _non_empty_string(metadata.get(field_name)):
                failures.append(f"metadata.{field_name} must be a non-empty string")
    archetype = spec.get("environment_archetype")
    if isinstance(archetype, str) and archetype not in ARCHETYPE_PROFILES:
        failures.append(f"environment_archetype must be one of {', '.join(sorted(ARCHETYPE_PROFILES))}")
    latency_budget = spec.get("latency_budget_ms")
    if isinstance(latency_budget, int) and latency_budget <= 0:
        failures.append("latency_budget_ms must be positive")
    for field_name in ("evidence_adapters_required", "expected_hypotheses", "forbidden_actions"):
        value = spec.get(field_name)
        if isinstance(value, list) and not value:
            failures.append(f"{field_name} must be a non-empty list")
    for field_name in ("evidence_adapters_required", "expected_hypotheses", "expected_action_templates", "forbidden_actions"):
        failures.extend(_validate_string_list(spec.get(field_name), field_name))
    adapter_ids = {contract.adapter_id for contract in default_provider_contracts()}
    for adapter in spec.get("evidence_adapters_required", []) if isinstance(spec.get("evidence_adapters_required"), list) else []:
        if isinstance(adapter, str) and adapter not in adapter_ids:
            failures.append(f"evidence_adapters_required contains unknown adapter: {adapter}")
    variant_axes = spec.get("variant_axes", {})
    if isinstance(variant_axes, dict):
        collection_modes = variant_axes.get("collection_mode")
        if not isinstance(collection_modes, list) or "fixture" not in collection_modes:
            failures.append("variant_axes.collection_mode must include fixture")
        for axis, values in variant_axes.items():
            if not _non_empty_string(axis):
                failures.append("variant_axes keys must be non-empty strings")
            failures.extend(_validate_string_list(values, f"variant_axes.{axis}"))
    cross_incident = spec.get("cross_incident")
    if cross_incident is not None and not isinstance(cross_incident, dict):
        failures.append("cross_incident must be a mapping when present")
    return failures


def _validate_expect_contract(package: ScenarioPackage) -> list[str]:
    failures: list[str] = []
    expect = package.expect
    if not isinstance(expect, dict):
        return ["expect.yaml must be a mapping"]
    for field_name in ("expected_hypotheses", "expected_action_templates", "forbidden_actions"):
        if field_name in expect:
            failures.extend(_validate_string_list(expect.get(field_name), field_name))
    if "requires_action_abstention" in expect and not isinstance(expect["requires_action_abstention"], bool):
        failures.append("requires_action_abstention must be a boolean")
    wait_for = expect.get("wait_for")
    if wait_for is None:
        return failures
    if not isinstance(wait_for, dict):
        return failures + ["wait_for must be a mapping"]
    if not _non_empty_string(wait_for.get("description")):
        failures.append("wait_for.description must be a non-empty string")
    for field_name in ("timeout_seconds", "interval_seconds"):
        value = wait_for.get(field_name)
        if not isinstance(value, (int, float)) or value <= 0:
            failures.append(f"wait_for.{field_name} must be a positive number")
    predicates = wait_for.get("predicates")
    if not isinstance(predicates, list) or not predicates:
        return failures + ["wait_for.predicates must be a non-empty list"]
    known_predicates = default_predicates()
    archetype = str(package.spec.get("environment_archetype") or "")
    for index, predicate in enumerate(predicates):
        prefix = f"wait_for.predicates[{index}]"
        if not isinstance(predicate, dict):
            failures.append(f"{prefix} must be a mapping")
            continue
        kind = predicate.get("kind")
        if not _non_empty_string(kind):
            failures.append(f"{prefix}.kind must be a non-empty string")
            continue
        registered = known_predicates.get(str(kind))
        if registered is None:
            failures.append(f"{prefix}.kind is not supported: {kind}")
            continue
        if archetype and archetype not in registered.archetypes:
            failures.append(f"{prefix}.kind {kind} does not support archetype {archetype}")
    return failures


def _validate_fixture_output_references(package: ScenarioPackage) -> list[str]:
    failures: list[str] = []
    contracts = {contract.adapter_id: contract for contract in default_provider_contracts()}
    output_dir = package.fixture_path / "outputs"
    adapters = package.spec.get("evidence_adapters_required", [])
    if not isinstance(adapters, list):
        return failures
    for adapter_id in adapters:
        if not isinstance(adapter_id, str):
            continue
        contract = contracts.get(adapter_id)
        if contract is None:
            continue
        output_path = output_dir / f"{contract.fixture_key}.txt"
        if not output_path.is_file():
            failures.append(f"fixture output is missing for {adapter_id}: {output_path}")
    return failures


def validate_variant_selection(package: ScenarioPackage, variants: dict[str, str]) -> list[str]:
    failures: list[str] = []
    axes = package.spec.get("variant_axes", {})
    if not isinstance(axes, dict):
        return ["variant_axes must be a mapping"]
    unknown = sorted(set(variants) - set(axes))
    failures.extend(f"unknown variant axis: {axis}" for axis in unknown)
    for axis, value in variants.items():
        allowed = axes.get(axis, [])
        if axis == "collection_mode" and value in COLLECTION_MODES:
            continue
        if isinstance(allowed, list) and allowed and value not in [str(item) for item in allowed]:
            failures.append(f"invalid variant {axis}={value}; expected one of {', '.join(map(str, allowed))}")
    return failures


def default_variant_selection(package: ScenarioPackage, requested: dict[str, str] | None = None) -> dict[str, str]:
    requested = requested or {}
    axes = package.spec.get("variant_axes", {})
    if not isinstance(axes, dict):
        return dict(requested)
    selected: dict[str, str] = {}
    for axis, values in axes.items():
        if axis in requested:
            selected[axis] = requested[axis]
        elif isinstance(values, list) and values:
            selected[axis] = str(values[0])
    return selected


def parse_variant_args(values: list[str] | None) -> dict[str, str]:
    variants: dict[str, str] = {}
    for value in values or []:
        if "=" not in value:
            raise ValueError(f"Variant must use axis=value: {value}")
        axis, selected = value.split("=", 1)
        if not axis or not selected:
            raise ValueError(f"Variant must use axis=value: {value}")
        variants[axis] = selected
    return variants


def scenario_incident_identity(
    package: ScenarioPackage,
    *,
    incident_id: str | None,
    incident_session_id: str,
) -> dict[str, Any]:
    cross_incident = package.cross_incident
    service_id = _string_or_none(cross_incident.get("service_catalog_id") or cross_incident.get("service_id"))
    resolved: dict[str, Any] = {
        "incident_id": _string_or_none(incident_id) or _string_or_none(cross_incident.get("incident_id")) or incident_session_id,
        "incident_session_id": incident_session_id,
        "scenario": package.name,
        "scenario_path": str(package.path),
    }
    if service_id:
        resolved["service_id"] = service_id
        resolved["service_catalog_id"] = service_id
    if isinstance(cross_incident.get("deploy_metadata"), dict):
        resolved["deploy_metadata"] = copy.deepcopy(cross_incident["deploy_metadata"])
    if isinstance(cross_incident.get("observability_tags"), (list, dict)):
        resolved["observability_tags"] = copy.deepcopy(cross_incident["observability_tags"])
    return resolved


def stand_up_incident_environment(
    package: ScenarioPackage,
    *,
    variants: dict[str, str] | None = None,
    collection_mode: str | None = None,
    incident_id: str | None = None,
    incident_session_id: str = "incident-generator-run",
    require_tools: bool = False,
    workdir: Path | None = None,
    hold_seconds: float | None = None,
    dispatch_archetype_func: Any = dispatch_archetype,
    seed_executor: Any | None = None,
    symptom_waiter: Any | None = None,
    resolve_selectors_func: Any = resolve_selectors,
    start_port_forwards_func: Any = start_port_forwards,
    rewrite_endpoints_func: Any = rewrite_endpoints_for_local_ports,
) -> dict[str, Any]:
    requested = dict(variants or {})
    if collection_mode is not None:
        requested["collection_mode"] = collection_mode
    selected = default_variant_selection(package, requested)
    mode = selected.get("collection_mode", "fixture")
    identity = scenario_incident_identity(package, incident_id=incident_id, incident_session_id=incident_session_id)

    validation_failures = validate_scenario_package(package)
    validation_failures.extend(validate_variant_selection(package, selected))
    if mode not in COLLECTION_MODES:
        validation_failures.append(f"unsupported collection_mode: {mode}")
    if validation_failures:
        return _blocked_result(package, selected, validation_failures, identity=identity)

    if mode == "fixture":
        return {
            "scenario": package.name,
            "scenario_path": str(package.path),
            "collection_mode": mode,
            "variants": dict(sorted(selected.items())),
            "incident_id": identity.get("incident_id"),
            "incident_session_id": identity.get("incident_session_id"),
            "service_id": identity.get("service_id"),
            "generated": True,
            "blocked": False,
            "deterministic": True,
            "environment_archetype": "fixture",
            "fixture": str(package.fixture_path),
            "skill_under_test": str(package.skill_path),
            "context": {"note": "fixture mode uses checked-in deterministic evidence and does not start live infrastructure"},
            "precondition_failures": [],
            "seed_failures": [],
            "wait_for_failures": [],
            "selector_failures": [],
            "port_forward_failures": [],
        }

    workdir = workdir or _project_root_for(package.path)
    archetype = str(package.spec.get("environment_archetype") or "")
    port_forward_run = None
    seed_result = None
    selector_result = None
    active_profile = None
    ctx: ArchetypeContext | None = None
    try:
        try:
            ctx = dispatch_archetype_func(archetype, package=package, workdir=workdir)
        except ValueError as exc:
            return _blocked_result(package, selected, [str(exc)], identity=identity)
        if ctx.precondition_failures:
            if require_tools or archetype not in FALLBACK_ARCHETYPES:
                return _blocked_result(
                    package,
                    selected,
                    _precondition_failure_reasons(ctx.precondition_failures),
                    identity=identity,
                    precondition_failures=ctx.precondition_failures,
                )
            return {
                **stand_up_incident_environment(
                    package,
                    variants={**selected, "collection_mode": "fixture"},
                    incident_id=incident_id,
                    incident_session_id=incident_session_id,
                    require_tools=require_tools,
                    workdir=workdir,
                ),
                "context": {
                    "archetype_fallback": {
                        "archetype": archetype,
                        "reason": "archetype tools not present, falling back to fixture mode",
                        "precondition_failures": copy.deepcopy(ctx.precondition_failures),
                    }
                },
            }

        seed_executor = seed_executor or SeedExecutor()
        seed_result = seed_executor.apply(package, ctx)
        if seed_result.failures:
            return _blocked_result(
                package,
                selected,
                _failure_reasons(seed_result.failures),
                identity=identity,
                seed_failures=seed_result.failures,
            )

        active_profile = ctx.provider_profile
        port_forward_run = start_port_forwards_func(ctx, active_profile)
        if port_forward_run.failures:
            return _blocked_result(
                package,
                selected,
                _failure_reasons(port_forward_run.failures),
                identity=identity,
                port_forward_failures=port_forward_run.failures,
            )
        if active_profile is not None and port_forward_run.forwards:
            active_profile = rewrite_endpoints_func(active_profile, port_forward_run.forwards)
        if active_profile is not None:
            ctx.host_env.update(resolve_environment(active_profile, ctx.host_env))

        symptom_waiter = symptom_waiter or SymptomWaiter()
        wait_result = symptom_waiter.wait(package, ctx, package.spec.get("inputs", {}))
        if wait_result.failures:
            return _blocked_result(
                package,
                selected,
                _failure_reasons(wait_result.failures),
                identity=identity,
                wait_for_failures=wait_result.failures,
            )

        selector_result = resolve_selectors_func(package, ctx)
        if selector_result.failures:
            return _blocked_result(
                package,
                selected,
                _failure_reasons(selector_result.failures),
                identity=identity,
                selector_failures=selector_result.failures,
            )

        if hold_seconds is not None:
            _hold_runtime(hold_seconds)

        return {
            "scenario": package.name,
            "scenario_path": str(package.path),
            "collection_mode": mode,
            "variants": dict(sorted(selected.items())),
            "incident_id": identity.get("incident_id"),
            "incident_session_id": identity.get("incident_session_id"),
            "service_id": identity.get("service_id"),
            "generated": True,
            "blocked": False,
            "deterministic": True,
            "environment_archetype": ctx.archetype,
            "fixture": str(package.fixture_path),
            "skill_under_test": str(package.skill_path),
            "precondition_failures": [],
            "seed_failures": [],
            "wait_for_failures": [],
            "selector_failures": [],
            "port_forward_failures": [],
            "context": _runtime_context(ctx, seed_result, selector_result, port_forward_run, active_profile),
        }
    except KeyboardInterrupt:
        return _blocked_result(package, selected, ["interrupted while holding generated environment"], identity=identity)
    finally:
        _teardown_runtime(port_forward_run, seed_result, seed_executor, package, ctx)


def _dispatch_kind(
    *,
    workdir: Path,
    host_env: dict[str, str],
    provider_profile: ProviderProfile | None,
    tool_lookup: ToolLookup,
    command_runner: SubprocessBoundary,
) -> ArchetypeContext:
    failures = _missing_tool_failures(("kind", "kubectl"), tool_lookup)
    if failures:
        return ArchetypeContext(
            archetype="kind",
            host_env=host_env,
            provider_profile=provider_profile,
            precondition_failures=failures,
        )

    tmp_dir = workdir / ".tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(prefix="kubeconfig-kind-", dir=tmp_dir, delete=False)
    handle.close()
    kubeconfig_path = Path(handle.name)
    runtime_env = {
        **host_env,
        "SRE_AGENT_KIND_KUBECONFIG": str(kubeconfig_path),
        "KUBECONFIG": str(kubeconfig_path),
    }
    up_script = workdir / "harness/archetypes/kind/up.sh"
    down_script = workdir / "harness/archetypes/kind/down.sh"
    observability_script = workdir / "harness/archetypes/kind/install-observability.sh"

    def teardown() -> None:
        command_runner([str(down_script)], env=runtime_env, cwd=workdir)

    completed = command_runner([str(up_script)], env=runtime_env, cwd=workdir)
    if completed.returncode != 0:
        return ArchetypeContext(
            archetype="kind",
            host_env=runtime_env,
            provider_profile=provider_profile,
            teardown=teardown,
            kubeconfig_path=str(kubeconfig_path),
            precondition_failures=[{"check": "kind_up", "error": _command_error(completed, "kind archetype bring-up failed")}],
        )
    completed = command_runner([str(observability_script)], env=runtime_env, cwd=workdir)
    if completed.returncode != 0:
        return ArchetypeContext(
            archetype="kind",
            host_env=runtime_env,
            provider_profile=provider_profile,
            teardown=teardown,
            kubeconfig_path=str(kubeconfig_path),
            precondition_failures=[
                {"check": "kind_observability", "error": _command_error(completed, "kind observability install failed")}
            ],
        )
    return ArchetypeContext(
        archetype="kind",
        host_env=runtime_env,
        provider_profile=provider_profile,
        teardown=teardown,
        kubeconfig_path=str(kubeconfig_path),
    )


def _dispatch_linux_vm(
    *,
    package: ScenarioPackage,
    workdir: Path,
    host_env: dict[str, str],
    provider_profile: ProviderProfile | None,
    tool_lookup: ToolLookup,
    command_runner: SubprocessBoundary,
) -> ArchetypeContext:
    failures = _missing_tool_failures(("docker",), tool_lookup)
    if not failures:
        compose_version = command_runner(["docker", "compose", "version"], env=host_env, cwd=workdir)
        if compose_version.returncode != 0:
            failures.append(
                {"check": "docker_compose", "error": _command_error(compose_version, "docker compose v2 plugin is required")}
            )
    if failures:
        return ArchetypeContext(
            archetype="linux-vm",
            host_env=host_env,
            provider_profile=provider_profile,
            precondition_failures=failures,
        )

    compose_file = workdir / "harness/archetypes/linux-vm/docker-compose.yaml"
    compose_project = f"incident-generator-{_slug(package.name)}"
    runtime_env = {**host_env, "COMPOSE_PROJECT_NAME": compose_project}
    up_args = ["docker", "compose", "-f", str(compose_file), "up", "-d"]
    if _truthy(runtime_env.get("INCIDENT_GENERATOR_LINUX_VM_REBUILD")) or _truthy(runtime_env.get("SRE_AGENT_LINUX_VM_REBUILD")):
        up_args.append("--build")
    down_args = ["docker", "compose", "-f", str(compose_file), "down", "--remove-orphans", "--volumes"]

    def teardown() -> None:
        command_runner(down_args, env=runtime_env, cwd=workdir)

    completed = command_runner(up_args, env=runtime_env, cwd=workdir)
    if completed.returncode != 0:
        return ArchetypeContext(
            archetype="linux-vm",
            host_env=runtime_env,
            provider_profile=provider_profile,
            teardown=teardown,
            compose_project=compose_project,
            precondition_failures=[
                {"check": "linux_vm_up", "error": _command_error(completed, "linux-vm archetype bring-up failed")}
            ],
        )
    return ArchetypeContext(
        archetype="linux-vm",
        host_env=runtime_env,
        provider_profile=provider_profile,
        teardown=teardown,
        compose_project=compose_project,
    )


def _blocked_result(
    package: ScenarioPackage,
    variants: dict[str, str],
    failures: list[str],
    *,
    identity: dict[str, Any],
    precondition_failures: list[dict[str, str]] | None = None,
    seed_failures: list[dict[str, Any]] | None = None,
    wait_for_failures: list[dict[str, Any]] | None = None,
    selector_failures: list[dict[str, Any]] | None = None,
    port_forward_failures: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    return {
        "scenario": package.name,
        "scenario_path": str(package.path),
        "collection_mode": variants.get("collection_mode", "fixture"),
        "variants": dict(sorted(variants.items())),
        "incident_id": identity.get("incident_id"),
        "incident_session_id": identity.get("incident_session_id"),
        "service_id": identity.get("service_id"),
        "generated": False,
        "blocked": True,
        "blocking_reasons": failures,
        "precondition_failures": copy.deepcopy(precondition_failures or []),
        "seed_failures": copy.deepcopy(seed_failures or []),
        "wait_for_failures": copy.deepcopy(wait_for_failures or []),
        "selector_failures": copy.deepcopy(selector_failures or []),
        "port_forward_failures": copy.deepcopy(port_forward_failures or []),
    }


def _runtime_context(
    ctx: ArchetypeContext,
    seed_result: Any,
    selector_result: Any,
    port_forward_run: Any,
    active_profile: ProviderProfile | None,
) -> dict[str, Any]:
    context: dict[str, Any] = {
        "archetype": ctx.archetype,
        "seed_applied": bool(seed_result.applied) if seed_result is not None else False,
    }
    if ctx.provider_profile is not None:
        context["provider_profile"] = ctx.provider_profile.name
    if active_profile is not None:
        context["active_provider_profile"] = active_profile.name
        context["provider_environment"] = dict(sorted(active_profile.environment.items()))
        context["provider_endpoints"] = dict(sorted(active_profile.endpoints.items()))
    if ctx.kubeconfig_path:
        context["kubeconfig_path"] = ctx.kubeconfig_path
    if ctx.compose_project:
        context["compose_project"] = ctx.compose_project
    if selector_result is not None:
        context["selector_resolution"] = copy.deepcopy(selector_result.metadata)
    if port_forward_run is not None:
        context["port_forwards"] = [
            {
                "service": forward.service,
                "namespace": forward.namespace,
                "remote_port": forward.remote_port,
                "local_port": forward.local_port,
            }
            for forward in port_forward_run.forwards
        ]
    return context


def _teardown_runtime(
    port_forward_run: Any | None,
    seed_result: Any | None,
    seed_executor: Any | None,
    package: ScenarioPackage,
    ctx: ArchetypeContext | None,
) -> None:
    if port_forward_run is not None:
        port_forward_run.stop_all()
    if seed_result is not None and seed_result.applied and seed_executor is not None and ctx is not None:
        seed_executor.teardown(package, ctx)
    if ctx is not None:
        ctx.teardown()


def _hold_runtime(hold_seconds: float) -> None:
    if hold_seconds < 0:
        while True:
            time.sleep(3600)
    else:
        time.sleep(hold_seconds)


def _missing_tool_failures(tools: tuple[str, ...], tool_lookup: ToolLookup) -> list[dict[str, str]]:
    return [
        {"check": tool, "error": f"{tool} is required for archetype dispatch"}
        for tool in tools
        if tool_lookup(tool) is None
    ]


def _precondition_failure_reasons(failures: list[dict[str, str]]) -> list[str]:
    return [f"{failure.get('check', 'precondition')}: {failure.get('error', 'failed')}" for failure in failures]


def _failure_reasons(failures: list[dict[str, Any]]) -> list[str]:
    return [f"{failure.get('check', 'check')}: {failure.get('error', 'failed')}" for failure in failures]


def _catalog_row(root: Path, package: ScenarioPackage) -> dict[str, Any]:
    failures = validate_scenario_package(package)
    variants = default_variant_selection(package)
    adapters = package.spec.get("evidence_adapters_required", [])
    return {
        "name": package.name,
        "domain": package.domain,
        "path": str(package.path.relative_to(root)),
        "environment_archetype": str(package.spec.get("environment_archetype") or ""),
        "variants": variants,
        "collection_modes": list(package.spec.get("variant_axes", {}).get("collection_mode", []))
        if isinstance(package.spec.get("variant_axes"), dict)
        else [],
        "evidence_adapters_required": list(adapters) if isinstance(adapters, list) else [],
        "live_readiness": _live_readiness(package, failures),
        "valid": not failures,
        "failures": failures,
    }


def _live_readiness(package: ScenarioPackage, failures: list[str]) -> str:
    if failures:
        return "blocked:invalid"
    axes = package.spec.get("variant_axes", {})
    collection_modes = axes.get("collection_mode", []) if isinstance(axes, dict) else []
    if "real" not in collection_modes:
        return "fixture-only"
    archetype = str(package.spec.get("environment_archetype") or "")
    if archetype == "eks-staging":
        return "blocked:eks-staging"
    if archetype in FALLBACK_ARCHETYPES:
        return "local-real"
    return "blocked:unsupported-archetype"


def _counter_dict(values: Any) -> dict[str, int]:
    return dict(sorted(Counter(str(value) for value in values).items()))


def _group_rows(rows: list[dict[str, Any]], key: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get(key) or "")].append(row)
    return dict(sorted(grouped.items()))


def _run_subprocess(
    args: list[str],
    *,
    env: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=cwd,
        env=dict(env) if env is not None else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _command_error(completed: subprocess.CompletedProcess[str], fallback: str) -> str:
    detail = (completed.stderr or completed.stdout or "").strip()
    return detail or fallback


def _project_root_for(path: Path) -> Path:
    current = path.resolve()
    for candidate in (current, *current.parents):
        if (candidate / "scenarios").is_dir() and (candidate / "harness").is_dir():
            return candidate
    return Path.cwd()


def _resolve_path(root: Path, raw_path: str) -> Path:
    path = Path(raw_path)
    if path.is_absolute():
        return path
    candidate = root / path
    if candidate.exists():
        return candidate
    project_candidate = _project_root_for(root) / path
    return project_candidate


def _validate_string_list(value: Any, field_name: str) -> list[str]:
    if not isinstance(value, list):
        return [f"{field_name} must be a list"]
    failures: list[str] = []
    for index, item in enumerate(value):
        if not _non_empty_string(item):
            failures.append(f"{field_name}[{index}] must be a non-empty string")
    return failures


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _type_name(value: type | tuple[type, ...]) -> str:
    if isinstance(value, tuple):
        return " or ".join(item.__name__ for item in value)
    return value.__name__


def _truthy(value: str | None) -> bool:
    return str(value or "").lower() in {"1", "true", "yes", "on"}


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9-]+", "-", value.lower()).strip("-") or "scenario"


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None
