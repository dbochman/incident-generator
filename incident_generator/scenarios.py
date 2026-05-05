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
from .progress import NoopProgressReporter, progress_artifacts
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


def _noop_teardown_verifier() -> list[dict[str, str]]:
    return []


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

    @property
    def resource_claims(self) -> list[dict[str, Any]]:
        value = self.spec.get("resource_claims", [])
        return copy.deepcopy(value) if isinstance(value, list) else []


@dataclass
class ArchetypeContext:
    archetype: str
    host_env: dict[str, str]
    provider_profile: ProviderProfile | None = None
    teardown: Callable[[], None] = _noop_teardown
    teardown_verifier: Callable[[], list[dict[str, str]]] = _noop_teardown_verifier
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
    resource_claims = spec.get("resource_claims")
    if resource_claims is not None:
        failures.extend(_validate_resource_claims(resource_claims))
    return failures


def _validate_resource_claims(value: Any) -> list[str]:
    if not isinstance(value, list):
        return ["resource_claims must be a list when present"]
    failures: list[str] = []
    for index, claim in enumerate(value):
        field = f"resource_claims[{index}]"
        if not isinstance(claim, dict):
            failures.append(f"{field} must be a mapping")
            continue
        for name in ("kind", "name", "mode"):
            if not _non_empty_string(claim.get(name)):
                failures.append(f"{field}.{name} must be a non-empty string")
        mode = claim.get("mode")
        if isinstance(mode, str) and mode not in {"exclusive", "shared"}:
            failures.append(f"{field}.mode must be exclusive or shared")
        scopes = claim.get("scope", "real")
        if isinstance(scopes, str):
            scope_values = [scopes]
        elif isinstance(scopes, list):
            scope_values = scopes
            failures.extend(_validate_string_list(scopes, f"{field}.scope"))
        else:
            scope_values = []
            failures.append(f"{field}.scope must be a string or list")
        invalid_scopes = sorted(str(scope) for scope in scope_values if scope not in COLLECTION_MODES)
        if invalid_scopes:
            failures.append(f"{field}.scope contains unsupported collection_mode: {', '.join(invalid_scopes)}")
        namespace = claim.get("namespace")
        if namespace is not None and not _non_empty_string(namespace):
            failures.append(f"{field}.namespace must be a non-empty string when present")
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


def combinatorial_incident_identity(
    packages: list[ScenarioPackage],
    *,
    incident_id: str | None,
    incident_session_id: str,
) -> dict[str, Any]:
    incident_ids = _unique_strings(
        package.cross_incident.get("incident_id")
        for package in packages
        if isinstance(package.cross_incident, dict)
    )
    service_ids = _unique_strings(
        (package.cross_incident.get("service_catalog_id") or package.cross_incident.get("service_id"))
        for package in packages
        if isinstance(package.cross_incident, dict)
    )
    resolved: dict[str, Any] = {
        "incident_id": _string_or_none(incident_id) or (incident_ids[0] if len(incident_ids) == 1 else incident_session_id),
        "incident_session_id": incident_session_id,
        "scenario": _combined_scenario_name(packages),
        "scenarios": [package.name for package in packages],
    }
    if len(service_ids) == 1:
        resolved["service_id"] = service_ids[0]
        resolved["service_catalog_id"] = service_ids[0]
    if service_ids:
        resolved["service_ids"] = service_ids
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
    progress_reporter: Any | None = None,
) -> dict[str, Any]:
    progress = progress_reporter or NoopProgressReporter()
    requested = dict(variants or {})
    if collection_mode is not None:
        requested["collection_mode"] = collection_mode
    selected = default_variant_selection(package, requested)
    mode = selected.get("collection_mode", "fixture")
    identity = scenario_incident_identity(package, incident_id=incident_id, incident_session_id=incident_session_id)

    progress.emit(
        "run",
        "started",
        package.name,
        details={
            "scenario_path": str(package.path),
            "collection_mode": mode,
            "incident_id": identity.get("incident_id"),
            "incident_session_id": identity.get("incident_session_id"),
            "variants": dict(sorted(selected.items())),
        },
    )
    progress.emit("validate", "started", "validating scenario contract")
    validation_failures = validate_scenario_package(package)
    validation_failures.extend(validate_variant_selection(package, selected))
    if mode not in COLLECTION_MODES:
        validation_failures.append(f"unsupported collection_mode: {mode}")
    if validation_failures:
        progress.emit("validate", "failed", "scenario validation failed", details={"failures": validation_failures})
        result = _blocked_result(package, selected, validation_failures, identity=identity)
        return _complete_progress_result(result, progress)
    progress.emit("validate", "ok", "scenario contract is valid")

    if mode == "fixture":
        progress.emit("fixture", "ok", "using checked-in deterministic evidence", details={"fixture": str(package.fixture_path)})
        result = {
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
        return _complete_progress_result(result, progress)

    workdir = workdir or _project_root_for(package.path)
    archetype = str(package.spec.get("environment_archetype") or "")
    port_forward_run = None
    seed_result = None
    selector_result = None
    active_profile = None
    ctx: ArchetypeContext | None = None
    result: dict[str, Any] | None = None
    try:
        try:
            progress.emit("archetype", "started", f"starting {archetype}", details={"archetype": archetype})
            ctx = dispatch_archetype_func(archetype, package=package, workdir=workdir)
        except ValueError as exc:
            progress.emit("archetype", "failed", str(exc), details={"archetype": archetype})
            result = _blocked_result(package, selected, [str(exc)], identity=identity)
            return result
        if ctx.precondition_failures:
            if require_tools or archetype not in FALLBACK_ARCHETYPES:
                progress.emit(
                    "archetype",
                    "failed",
                    f"{archetype} preconditions failed",
                    details={"precondition_failures": ctx.precondition_failures},
                )
                result = _blocked_result(
                    package,
                    selected,
                    _precondition_failure_reasons(ctx.precondition_failures),
                    identity=identity,
                    precondition_failures=ctx.precondition_failures,
                )
                return result
            progress.emit(
                "archetype",
                "fallback",
                f"{archetype} tools missing; falling back to fixture mode",
                details={"precondition_failures": ctx.precondition_failures},
            )
            result = {
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
            return result
        progress.emit(
            "archetype",
            "ok",
            f"{archetype} ready",
            details={
                "archetype": ctx.archetype,
                "kubeconfig_path": ctx.kubeconfig_path,
                "compose_project": ctx.compose_project,
            },
        )

        seed_executor = seed_executor or SeedExecutor()
        progress.emit("seed", "started", "applying scenario seed")
        seed_result = seed_executor.apply(package, ctx)
        if seed_result.failures:
            progress.emit("seed", "failed", "scenario seed failed", details={"failures": seed_result.failures})
            result = _blocked_result(
                package,
                selected,
                _failure_reasons(seed_result.failures),
                identity=identity,
                seed_failures=seed_result.failures,
            )
            return result
        progress.emit(
            "seed",
            "ok",
            "scenario seed applied" if seed_result.applied else "scenario seed skipped",
            details={"applied": seed_result.applied},
        )

        active_profile = ctx.provider_profile
        progress.emit("port_forward", "started", "starting provider port-forwards")
        port_forward_run = start_port_forwards_func(ctx, active_profile)
        if port_forward_run.failures:
            progress.emit("port_forward", "failed", "provider port-forward failed", details={"failures": port_forward_run.failures})
            result = _blocked_result(
                package,
                selected,
                _failure_reasons(port_forward_run.failures),
                identity=identity,
                port_forward_failures=port_forward_run.failures,
            )
            return result
        progress.emit(
            "port_forward",
            "ok",
            "provider port-forwards ready" if port_forward_run.forwards else "no provider port-forwards required",
            details={"forwards": _port_forward_details(port_forward_run)},
        )
        if active_profile is not None and port_forward_run.forwards:
            active_profile = rewrite_endpoints_func(active_profile, port_forward_run.forwards)
        if active_profile is not None:
            ctx.host_env.update(resolve_environment(active_profile, ctx.host_env))
            progress.emit(
                "providers",
                "ok",
                "provider endpoints available",
                details={"endpoints": dict(sorted(active_profile.endpoints.items()))},
            )

        symptom_waiter = symptom_waiter or SymptomWaiter(progress_reporter=progress)
        wait_result = symptom_waiter.wait(package, ctx, package.spec.get("inputs", {}))
        if wait_result.failures:
            result = _blocked_result(
                package,
                selected,
                _failure_reasons(wait_result.failures),
                identity=identity,
                wait_for_failures=wait_result.failures,
            )
            return result

        progress.emit("selector", "started", "resolving live target selectors")
        selector_result = resolve_selectors_func(package, ctx)
        if selector_result.failures:
            progress.emit("selector", "failed", "selector resolution failed", details={"failures": selector_result.failures})
            result = _blocked_result(
                package,
                selected,
                _failure_reasons(selector_result.failures),
                identity=identity,
                selector_failures=selector_result.failures,
            )
            return result
        progress.emit("selector", "ok", "selectors resolved", details={"selector_resolution": selector_result.metadata})

        if hold_seconds is not None:
            progress.emit(
                "hold",
                "started",
                "holding generated environment",
                details={"hold_seconds": hold_seconds if hold_seconds >= 0 else None},
            )
            _hold_runtime(hold_seconds)
            progress.emit("hold", "ok", "hold complete")

        result = {
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
        return result
    except KeyboardInterrupt:
        progress.emit("hold", "interrupted", "interrupted while holding generated environment")
        result = _blocked_result(package, selected, ["interrupted while holding generated environment"], identity=identity)
        return result
    finally:
        teardown_failures = _teardown_runtime(
            port_forward_run,
            seed_result,
            seed_executor,
            package,
            ctx,
            progress_reporter=progress,
        )
        if result is not None and ctx is not None:
            result["teardown_failures"] = teardown_failures
            result.setdefault("context", {})["teardown"] = {
                "verified": not teardown_failures,
                "failures": copy.deepcopy(teardown_failures),
            }
        if result is not None:
            _complete_progress_result(result, progress)


def stand_up_combinatorial_incident_environment(
    packages: list[ScenarioPackage],
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
    progress_reporter: Any | None = None,
) -> dict[str, Any]:
    progress = progress_reporter or NoopProgressReporter()
    package_list = list(packages)
    requested = dict(variants or {})
    if collection_mode is not None:
        requested["collection_mode"] = collection_mode
    selected_variants, variant_failures = _combined_variant_selections(package_list, requested)
    mode = _combined_collection_mode(selected_variants)
    identity = combinatorial_incident_identity(
        package_list,
        incident_id=incident_id,
        incident_session_id=incident_session_id,
    )

    progress.emit(
        "run",
        "started",
        identity["scenario"],
        details={
            "combined": True,
            "scenario_count": len(package_list),
            "scenarios": [package.name for package in package_list],
            "collection_mode": mode,
            "incident_id": identity.get("incident_id"),
            "incident_session_id": identity.get("incident_session_id"),
            "variants": _variant_sets(package_list, selected_variants),
        },
    )
    progress.emit("validate", "started", "validating combinatorial scenario contract")
    validation_failures = _validate_combinatorial_incident(package_list, selected_variants, mode, variant_failures)
    if validation_failures:
        progress.emit("validate", "failed", "combinatorial validation failed", details={"failures": validation_failures})
        result = _blocked_combinatorial_result(
            package_list,
            selected_variants,
            validation_failures,
            identity=identity,
            collection_mode=mode,
        )
        return _complete_progress_result(result, progress)
    progress.emit("validate", "ok", "combinatorial scenario contract is valid")

    if mode == "fixture":
        progress.emit(
            "fixture",
            "ok",
            "using checked-in deterministic evidence for combined scenarios",
            details={"fixtures": [_path_text(package.fixture_path) for package in package_list]},
        )
        result = _combinatorial_fixture_result(package_list, selected_variants, identity=identity)
        return _complete_progress_result(result, progress)

    workdir = workdir or _project_root_for(package_list[0].path)
    archetype = str(package_list[0].spec.get("environment_archetype") or "")
    port_forward_run = None
    seed_records: list[tuple[ScenarioPackage, Any]] = []
    selector_records: list[tuple[ScenarioPackage, Any]] = []
    active_profile = None
    ctx: ArchetypeContext | None = None
    result: dict[str, Any] | None = None
    try:
        try:
            progress.emit("archetype", "started", f"starting {archetype}", details={"archetype": archetype})
            ctx = dispatch_archetype_func(archetype, package=package_list[0], workdir=workdir)
        except ValueError as exc:
            progress.emit("archetype", "failed", str(exc), details={"archetype": archetype})
            result = _blocked_combinatorial_result(
                package_list,
                selected_variants,
                [str(exc)],
                identity=identity,
                collection_mode=mode,
            )
            return result
        if ctx.precondition_failures:
            if require_tools or archetype not in FALLBACK_ARCHETYPES:
                progress.emit(
                    "archetype",
                    "failed",
                    f"{archetype} preconditions failed",
                    details={"precondition_failures": ctx.precondition_failures},
                )
                result = _blocked_combinatorial_result(
                    package_list,
                    selected_variants,
                    _precondition_failure_reasons(ctx.precondition_failures),
                    identity=identity,
                    collection_mode=mode,
                    precondition_failures=ctx.precondition_failures,
                )
                return result
            progress.emit(
                "archetype",
                "fallback",
                f"{archetype} tools missing; falling back to fixture mode",
                details={"precondition_failures": ctx.precondition_failures},
            )
            fixture_variants = [{**selection, "collection_mode": "fixture"} for selection in selected_variants]
            result = _combinatorial_fixture_result(package_list, fixture_variants, identity=identity)
            result["context"]["archetype_fallback"] = {
                "archetype": archetype,
                "reason": "archetype tools not present, falling back to fixture mode",
                "precondition_failures": copy.deepcopy(ctx.precondition_failures),
            }
            return result
        progress.emit(
            "archetype",
            "ok",
            f"{archetype} ready",
            details={
                "archetype": ctx.archetype,
                "kubeconfig_path": ctx.kubeconfig_path,
                "compose_project": ctx.compose_project,
            },
        )

        seed_executor = seed_executor or SeedExecutor()
        for package in package_list:
            progress.emit("seed", "started", f"applying scenario seed: {package.name}", details={"scenario": package.name})
            seed_result = seed_executor.apply(package, ctx)
            seed_records.append((package, seed_result))
            if seed_result.failures:
                progress.emit(
                    "seed",
                    "failed",
                    f"scenario seed failed: {package.name}",
                    details={"scenario": package.name, "failures": seed_result.failures},
                )
                result = _blocked_combinatorial_result(
                    package_list,
                    selected_variants,
                    _scenario_failure_reasons(package, seed_result.failures),
                    identity=identity,
                    collection_mode=mode,
                    seed_failures=_annotated_failures(package, seed_result.failures),
                )
                return result
            progress.emit(
                "seed",
                "ok",
                f"scenario seed applied: {package.name}" if seed_result.applied else f"scenario seed skipped: {package.name}",
                details={"scenario": package.name, "applied": seed_result.applied},
            )

        active_profile = ctx.provider_profile
        progress.emit("port_forward", "started", "starting provider port-forwards")
        port_forward_run = start_port_forwards_func(ctx, active_profile)
        if port_forward_run.failures:
            progress.emit("port_forward", "failed", "provider port-forward failed", details={"failures": port_forward_run.failures})
            result = _blocked_combinatorial_result(
                package_list,
                selected_variants,
                _failure_reasons(port_forward_run.failures),
                identity=identity,
                collection_mode=mode,
                port_forward_failures=port_forward_run.failures,
            )
            return result
        progress.emit(
            "port_forward",
            "ok",
            "provider port-forwards ready" if port_forward_run.forwards else "no provider port-forwards required",
            details={"forwards": _port_forward_details(port_forward_run)},
        )
        if active_profile is not None and port_forward_run.forwards:
            active_profile = rewrite_endpoints_func(active_profile, port_forward_run.forwards)
        if active_profile is not None:
            ctx.host_env.update(resolve_environment(active_profile, ctx.host_env))
            progress.emit(
                "providers",
                "ok",
                "provider endpoints available",
                details={"endpoints": dict(sorted(active_profile.endpoints.items()))},
            )

        symptom_waiter = symptom_waiter or SymptomWaiter(progress_reporter=progress)
        for package in package_list:
            wait_result = symptom_waiter.wait(package, ctx, package.spec.get("inputs", {}))
            if wait_result.failures:
                result = _blocked_combinatorial_result(
                    package_list,
                    selected_variants,
                    _scenario_failure_reasons(package, wait_result.failures),
                    identity=identity,
                    collection_mode=mode,
                    wait_for_failures=_annotated_failures(package, wait_result.failures),
                )
                return result

        for package in package_list:
            progress.emit("selector", "started", f"resolving live target selectors: {package.name}", details={"scenario": package.name})
            selector_result = resolve_selectors_func(package, ctx)
            selector_records.append((package, selector_result))
            if selector_result.failures:
                progress.emit(
                    "selector",
                    "failed",
                    f"selector resolution failed: {package.name}",
                    details={"scenario": package.name, "failures": selector_result.failures},
                )
                result = _blocked_combinatorial_result(
                    package_list,
                    selected_variants,
                    _scenario_failure_reasons(package, selector_result.failures),
                    identity=identity,
                    collection_mode=mode,
                    selector_failures=_annotated_failures(package, selector_result.failures),
                )
                return result
            progress.emit(
                "selector",
                "ok",
                f"selectors resolved: {package.name}",
                details={"scenario": package.name, "selector_resolution": selector_result.metadata},
            )

        if hold_seconds is not None:
            progress.emit(
                "hold",
                "started",
                "holding generated environment",
                details={"hold_seconds": hold_seconds if hold_seconds >= 0 else None},
            )
            _hold_runtime(hold_seconds)
            progress.emit("hold", "ok", "hold complete")

        result = _combinatorial_success_result(
            package_list,
            selected_variants,
            identity=identity,
            collection_mode=mode,
            environment_archetype=ctx.archetype,
            context=_combinatorial_runtime_context(ctx, seed_records, selector_records, port_forward_run, active_profile),
        )
        return result
    except KeyboardInterrupt:
        progress.emit("hold", "interrupted", "interrupted while holding generated environment")
        result = _blocked_combinatorial_result(
            package_list,
            selected_variants,
            ["interrupted while holding generated environment"],
            identity=identity,
            collection_mode=mode,
        )
        return result
    finally:
        teardown_failures = _teardown_combinatorial_runtime(
            port_forward_run,
            seed_records,
            seed_executor,
            ctx,
            progress_reporter=progress,
        )
        if result is not None and ctx is not None:
            result["teardown_failures"] = teardown_failures
            result.setdefault("context", {})["teardown"] = {
                "verified": not teardown_failures,
                "failures": copy.deepcopy(teardown_failures),
            }
        if result is not None:
            _complete_progress_result(result, progress)


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

    def verify_teardown() -> list[dict[str, str]]:
        failures: list[dict[str, str]] = []
        cluster_name = runtime_env.get("SRE_AGENT_KIND_CLUSTER", "sre-agent-phase-a")
        clusters = command_runner(["kind", "get", "clusters"], env=runtime_env, cwd=workdir)
        if clusters.returncode == 0 and cluster_name in _split_lines(clusters.stdout):
            failures.append({"check": "kind_cluster_deleted", "error": f"kind cluster still exists: {cluster_name}"})
        if kubeconfig_path.exists():
            failures.append({"check": "kind_kubeconfig_removed", "error": f"kubeconfig still exists: {kubeconfig_path}"})
        return failures

    completed = command_runner([str(up_script)], env=runtime_env, cwd=workdir)
    if completed.returncode != 0:
        return ArchetypeContext(
            archetype="kind",
            host_env=runtime_env,
            provider_profile=provider_profile,
            teardown=teardown,
            teardown_verifier=verify_teardown,
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
            teardown_verifier=verify_teardown,
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
        teardown_verifier=verify_teardown,
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

    def verify_teardown() -> list[dict[str, str]]:
        failures: list[dict[str, str]] = []
        ps = command_runner(["docker", "compose", "-f", str(compose_file), "ps", "-q"], env=runtime_env, cwd=workdir)
        if ps.returncode == 0 and ps.stdout.strip():
            failures.append({"check": "linux_vm_compose_stopped", "error": "compose containers still exist"})
        volumes = command_runner(
            ["docker", "volume", "ls", "--filter", f"label=com.docker.compose.project={compose_project}", "-q"],
            env=runtime_env,
            cwd=workdir,
        )
        if volumes.returncode == 0 and volumes.stdout.strip():
            failures.append({"check": "linux_vm_volumes_removed", "error": "compose volumes still exist"})
        return failures

    completed = command_runner(up_args, env=runtime_env, cwd=workdir)
    if completed.returncode != 0:
        return ArchetypeContext(
            archetype="linux-vm",
            host_env=runtime_env,
            provider_profile=provider_profile,
            teardown=teardown,
            teardown_verifier=verify_teardown,
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
        teardown_verifier=verify_teardown,
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


def _blocked_combinatorial_result(
    packages: list[ScenarioPackage],
    selected_variants: list[dict[str, str]],
    failures: list[str],
    *,
    identity: dict[str, Any],
    collection_mode: str,
    precondition_failures: list[dict[str, str]] | None = None,
    seed_failures: list[dict[str, Any]] | None = None,
    wait_for_failures: list[dict[str, Any]] | None = None,
    selector_failures: list[dict[str, Any]] | None = None,
    port_forward_failures: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    result = _combinatorial_base_result(
        packages,
        selected_variants,
        identity=identity,
        collection_mode=collection_mode,
        generated=False,
        blocked=True,
    )
    result.update(
        {
            "blocking_reasons": failures,
            "precondition_failures": copy.deepcopy(precondition_failures or []),
            "seed_failures": copy.deepcopy(seed_failures or []),
            "wait_for_failures": copy.deepcopy(wait_for_failures or []),
            "selector_failures": copy.deepcopy(selector_failures or []),
            "port_forward_failures": copy.deepcopy(port_forward_failures or []),
        }
    )
    return result


def _combinatorial_fixture_result(
    packages: list[ScenarioPackage],
    selected_variants: list[dict[str, str]],
    *,
    identity: dict[str, Any],
) -> dict[str, Any]:
    result = _combinatorial_success_result(
        packages,
        selected_variants,
        identity=identity,
        collection_mode="fixture",
        environment_archetype="fixture",
        context={
            "note": "fixture mode uses checked-in deterministic evidence for each combined scenario and does not start live infrastructure"
        },
    )
    return result


def _combinatorial_success_result(
    packages: list[ScenarioPackage],
    selected_variants: list[dict[str, str]],
    *,
    identity: dict[str, Any],
    collection_mode: str,
    environment_archetype: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    result = _combinatorial_base_result(
        packages,
        selected_variants,
        identity=identity,
        collection_mode=collection_mode,
        generated=True,
        blocked=False,
    )
    result.update(
        {
            "deterministic": True,
            "environment_archetype": environment_archetype,
            "fixtures": [_path_text(package.fixture_path) for package in packages],
            "skills_under_test": [_path_text(package.skill_path) for package in packages],
            "precondition_failures": [],
            "seed_failures": [],
            "wait_for_failures": [],
            "selector_failures": [],
            "port_forward_failures": [],
            "context": context,
        }
    )
    return result


def _combinatorial_base_result(
    packages: list[ScenarioPackage],
    selected_variants: list[dict[str, str]],
    *,
    identity: dict[str, Any],
    collection_mode: str,
    generated: bool,
    blocked: bool,
) -> dict[str, Any]:
    service_ids = list(identity.get("service_ids") or [])
    result: dict[str, Any] = {
        "scenario": identity.get("scenario") or _combined_scenario_name(packages),
        "scenario_count": len(packages),
        "scenarios": _scenario_rows(packages, selected_variants),
        "combined": True,
        "collection_mode": collection_mode,
        "variant_sets": _variant_sets(packages, selected_variants),
        "incident_id": identity.get("incident_id"),
        "incident_session_id": identity.get("incident_session_id"),
        "service_id": identity.get("service_id"),
        "service_ids": service_ids,
        "generated": generated,
        "blocked": blocked,
        "evidence_adapters_required": _combined_string_field(packages, "evidence_adapters_required"),
        "expected_hypotheses": _combined_string_field(packages, "expected_hypotheses"),
        "expected_action_templates": _combined_string_field(packages, "expected_action_templates"),
        "forbidden_actions": _combined_string_field(packages, "forbidden_actions"),
        "success_criteria": _combined_success_criteria(packages),
        "latency_budget_ms": sum(
            value for value in (package.spec.get("latency_budget_ms") for package in packages) if isinstance(value, int)
        ),
    }
    if not service_ids:
        result.pop("service_ids")
    return result


def _combinatorial_runtime_context(
    ctx: ArchetypeContext,
    seed_records: list[tuple[ScenarioPackage, Any]],
    selector_records: list[tuple[ScenarioPackage, Any]],
    port_forward_run: Any,
    active_profile: ProviderProfile | None,
) -> dict[str, Any]:
    context: dict[str, Any] = {
        "archetype": ctx.archetype,
        "seed_results": [
            {"scenario": package.name, "applied": bool(getattr(seed_result, "applied", False))}
            for package, seed_result in seed_records
        ],
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
    if selector_records:
        context["selector_resolution"] = {
            package.name: copy.deepcopy(getattr(selector_result, "metadata", {}))
            for package, selector_result in selector_records
        }
    if port_forward_run is not None:
        context["port_forwards"] = _port_forward_details(port_forward_run)
    return context


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


def _complete_progress_result(result: dict[str, Any], progress_reporter: Any) -> dict[str, Any]:
    artifacts = progress_artifacts(progress_reporter)
    if artifacts:
        result.setdefault("context", {})["progress_artifacts"] = artifacts
    progress_reporter.emit(
        "run",
        "blocked" if result.get("blocked") else "ok",
        "incident generation blocked" if result.get("blocked") else "incident generation complete",
        details={
            "blocked": bool(result.get("blocked")),
            "generated": bool(result.get("generated")),
            "scenario": result.get("scenario"),
        },
    )
    progress_reporter.write_summary(result)
    return result


def _port_forward_details(port_forward_run: Any) -> list[dict[str, Any]]:
    return [
        {
            "service": forward.service,
            "namespace": forward.namespace,
            "remote_port": forward.remote_port,
            "local_port": forward.local_port,
        }
        for forward in getattr(port_forward_run, "forwards", [])
    ]


def _teardown_runtime(
    port_forward_run: Any | None,
    seed_result: Any | None,
    seed_executor: Any | None,
    package: ScenarioPackage,
    ctx: ArchetypeContext | None,
    *,
    progress_reporter: Any | None = None,
) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    progress = progress_reporter or NoopProgressReporter()
    if port_forward_run is not None or seed_result is not None or ctx is not None:
        progress.emit("teardown", "started", "tearing down generated environment")
    if port_forward_run is not None:
        try:
            progress.emit("teardown", "started", "stopping provider port-forwards", details={"step": "port_forward_stop"})
            port_forward_run.stop_all()
        except Exception as exc:  # pragma: no cover - defensive boundary for live cleanup.
            failures.append({"check": "port_forward_stop", "error": str(exc)})
            progress.emit("teardown", "failed", str(exc), details={"step": "port_forward_stop"})
        else:
            progress.emit("teardown", "ok", "provider port-forwards stopped", details={"step": "port_forward_stop"})
    if seed_result is not None and seed_result.applied and seed_executor is not None and ctx is not None:
        try:
            progress.emit("teardown", "started", "tearing down scenario seed", details={"step": "seed_teardown"})
            seed_executor.teardown(package, ctx)
        except Exception as exc:  # pragma: no cover - defensive boundary for live cleanup.
            failures.append({"check": "seed_teardown", "error": str(exc)})
            progress.emit("teardown", "failed", str(exc), details={"step": "seed_teardown"})
        else:
            progress.emit("teardown", "ok", "scenario seed teardown complete", details={"step": "seed_teardown"})
    if ctx is not None:
        try:
            progress.emit("teardown", "started", "tearing down archetype", details={"step": "archetype_teardown"})
            ctx.teardown()
        except Exception as exc:  # pragma: no cover - defensive boundary for live cleanup.
            failures.append({"check": "archetype_teardown", "error": str(exc)})
            progress.emit("teardown", "failed", str(exc), details={"step": "archetype_teardown"})
        else:
            progress.emit("teardown", "ok", "archetype teardown complete", details={"step": "archetype_teardown"})
        try:
            progress.emit("teardown", "started", "verifying teardown", details={"step": "teardown_verifier"})
            failures.extend(ctx.teardown_verifier())
        except Exception as exc:  # pragma: no cover - defensive boundary for live cleanup.
            failures.append({"check": "teardown_verifier", "error": str(exc)})
            progress.emit("teardown", "failed", str(exc), details={"step": "teardown_verifier"})
        else:
            progress.emit(
                "teardown",
                "ok" if not failures else "failed",
                "teardown verified" if not failures else "teardown verification found leftovers",
                details={"step": "teardown_verifier", "failures": copy.deepcopy(failures)},
            )
    return failures


def _teardown_combinatorial_runtime(
    port_forward_run: Any | None,
    seed_records: list[tuple[ScenarioPackage, Any]],
    seed_executor: Any | None,
    ctx: ArchetypeContext | None,
    *,
    progress_reporter: Any | None = None,
) -> list[dict[str, str]]:
    failures: list[dict[str, str]] = []
    progress = progress_reporter or NoopProgressReporter()
    if port_forward_run is not None or seed_records or ctx is not None:
        progress.emit("teardown", "started", "tearing down combined generated environment")
    if port_forward_run is not None:
        try:
            progress.emit("teardown", "started", "stopping provider port-forwards", details={"step": "port_forward_stop"})
            port_forward_run.stop_all()
        except Exception as exc:  # pragma: no cover - defensive boundary for live cleanup.
            failures.append({"check": "port_forward_stop", "error": str(exc)})
            progress.emit("teardown", "failed", str(exc), details={"step": "port_forward_stop"})
        else:
            progress.emit("teardown", "ok", "provider port-forwards stopped", details={"step": "port_forward_stop"})
    if seed_executor is not None and ctx is not None:
        for package, seed_result in reversed(seed_records):
            if not getattr(seed_result, "applied", False):
                continue
            try:
                progress.emit(
                    "teardown",
                    "started",
                    f"tearing down scenario seed: {package.name}",
                    details={"step": "seed_teardown", "scenario": package.name},
                )
                seed_executor.teardown(package, ctx)
            except Exception as exc:  # pragma: no cover - defensive boundary for live cleanup.
                failures.append({"check": "seed_teardown", "scenario": package.name, "error": str(exc)})
                progress.emit(
                    "teardown",
                    "failed",
                    str(exc),
                    details={"step": "seed_teardown", "scenario": package.name},
                )
            else:
                progress.emit(
                    "teardown",
                    "ok",
                    f"scenario seed teardown complete: {package.name}",
                    details={"step": "seed_teardown", "scenario": package.name},
                )
    if ctx is not None:
        try:
            progress.emit("teardown", "started", "tearing down archetype", details={"step": "archetype_teardown"})
            ctx.teardown()
        except Exception as exc:  # pragma: no cover - defensive boundary for live cleanup.
            failures.append({"check": "archetype_teardown", "error": str(exc)})
            progress.emit("teardown", "failed", str(exc), details={"step": "archetype_teardown"})
        else:
            progress.emit("teardown", "ok", "archetype teardown complete", details={"step": "archetype_teardown"})
        try:
            progress.emit("teardown", "started", "verifying teardown", details={"step": "teardown_verifier"})
            failures.extend(ctx.teardown_verifier())
        except Exception as exc:  # pragma: no cover - defensive boundary for live cleanup.
            failures.append({"check": "teardown_verifier", "error": str(exc)})
            progress.emit("teardown", "failed", str(exc), details={"step": "teardown_verifier"})
        else:
            progress.emit(
                "teardown",
                "ok" if not failures else "failed",
                "teardown verified" if not failures else "teardown verification found leftovers",
                details={"step": "teardown_verifier", "failures": copy.deepcopy(failures)},
            )
    return failures


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


def _scenario_failure_reasons(package: ScenarioPackage, failures: list[dict[str, Any]]) -> list[str]:
    return [f"{package.name}: {reason}" for reason in _failure_reasons(failures)]


def _annotated_failures(package: ScenarioPackage, failures: list[dict[str, Any]]) -> list[dict[str, Any]]:
    annotated: list[dict[str, Any]] = []
    for failure in failures:
        copied = copy.deepcopy(failure)
        copied.setdefault("scenario", package.name)
        copied.setdefault("scenario_path", _path_text(package.path))
        annotated.append(copied)
    return annotated


def _combined_variant_selections(
    packages: list[ScenarioPackage],
    requested: dict[str, str],
) -> tuple[list[dict[str, str]], list[str]]:
    known_axes: set[str] = set()
    for package in packages:
        axes = package.spec.get("variant_axes", {})
        if isinstance(axes, dict):
            known_axes.update(str(axis) for axis in axes)
    unknown = sorted(set(requested) - known_axes - {"collection_mode"})
    failures = [f"unknown variant axis for combination: {axis}" for axis in unknown]
    selections: list[dict[str, str]] = []
    for package in packages:
        axes = package.spec.get("variant_axes", {})
        package_axes = set(axes) if isinstance(axes, dict) else set()
        applicable = {axis: value for axis, value in requested.items() if axis == "collection_mode" or axis in package_axes}
        selection = default_variant_selection(package, applicable)
        if "collection_mode" in requested:
            selection["collection_mode"] = requested["collection_mode"]
        selections.append(selection)
    return selections, failures


def _combined_collection_mode(selected_variants: list[dict[str, str]]) -> str:
    modes = sorted({selection.get("collection_mode", "fixture") for selection in selected_variants})
    if not modes:
        return "fixture"
    if len(modes) > 1:
        return "mixed"
    return modes[0]


def _validate_combinatorial_incident(
    packages: list[ScenarioPackage],
    selected_variants: list[dict[str, str]],
    mode: str,
    variant_failures: list[str],
) -> list[str]:
    failures = list(variant_failures)
    if len(packages) < 2:
        failures.append("at least two scenarios are required for a combinatorial incident")
    paths = [package.path.resolve() for package in packages]
    duplicate_paths = sorted(str(path) for path, count in Counter(paths).items() if count > 1)
    failures.extend(f"duplicate scenario in combination: {path}" for path in duplicate_paths)
    if mode not in COLLECTION_MODES:
        if mode == "mixed":
            modes = sorted({selection.get("collection_mode", "fixture") for selection in selected_variants})
            failures.append(f"combinatorial scenarios must resolve to one collection_mode; got {', '.join(modes)}")
        else:
            failures.append(f"unsupported collection_mode: {mode}")
    for package, selection in zip(packages, selected_variants):
        failures.extend(f"{package.name}: {failure}" for failure in validate_scenario_package(package))
        failures.extend(f"{package.name}: {failure}" for failure in validate_variant_selection(package, selection))
    if mode == "real":
        archetypes = sorted({str(package.spec.get("environment_archetype") or "") for package in packages})
        if len(archetypes) != 1:
            failures.append(
                "real combinatorial incidents require all scenarios to use the same environment_archetype; "
                f"got {', '.join(archetypes)}"
            )
        failures.extend(scenario_resource_conflicts(packages, mode=mode))
    return failures


def scenario_resource_conflicts(packages: list[ScenarioPackage], *, mode: str = "real") -> list[str]:
    claims_by_resource: dict[str, set[str]] = defaultdict(set)
    for package in packages:
        for claim in _resource_claims_for_mode(package, mode):
            if claim.get("mode") != "exclusive":
                continue
            claims_by_resource[_resource_claim_key(claim)].add(package.name)
    failures: list[str] = []
    for resource, scenario_names in sorted(claims_by_resource.items()):
        if len(scenario_names) > 1:
            failures.append(f"scenarios share resource {resource}: {', '.join(sorted(scenario_names))}")
    return failures


def scenarios_are_compatible_for_mode(packages: list[ScenarioPackage], *, mode: str = "real") -> bool:
    return not scenario_resource_conflicts(packages, mode=mode)


def _resource_claims_for_mode(package: ScenarioPackage, mode: str) -> list[dict[str, str]]:
    claims: list[dict[str, str]] = []
    for claim in package.resource_claims:
        if not isinstance(claim, dict):
            continue
        scopes = claim.get("scope", "real")
        scope_values = [scopes] if isinstance(scopes, str) else scopes if isinstance(scopes, list) else []
        if mode not in scope_values:
            continue
        claims.append({str(key): str(value) for key, value in claim.items() if value is not None})
    return claims


def _resource_claim_key(claim: dict[str, str]) -> str:
    kind = claim.get("kind", "").strip()
    namespace = claim.get("namespace", "").strip()
    name = claim.get("name", "").strip()
    if namespace:
        return f"{kind}/{namespace}/{name}"
    return f"{kind}/{name}"


def _scenario_rows(packages: list[ScenarioPackage], selected_variants: list[dict[str, str]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for package, selection in zip(packages, selected_variants):
        metadata = package.spec.get("metadata", {})
        rows.append(
            {
                "name": package.name,
                "domain": package.domain,
                "symptom": str(metadata.get("symptom") or "") if isinstance(metadata, dict) else "",
                "variant": str(metadata.get("variant") or "") if isinstance(metadata, dict) else "",
                "path": _path_text(package.path),
                "environment_archetype": str(package.spec.get("environment_archetype") or ""),
                "variants": dict(sorted(selection.items())),
                "fixture": _path_text(package.fixture_path),
                "skill_under_test": _path_text(package.skill_path),
                "evidence_adapters_required": copy.deepcopy(package.spec.get("evidence_adapters_required", [])),
                "expected_hypotheses": copy.deepcopy(package.spec.get("expected_hypotheses", [])),
            }
        )
    return rows


def _variant_sets(packages: list[ScenarioPackage], selected_variants: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    return {package.name: dict(sorted(selection.items())) for package, selection in zip(packages, selected_variants)}


def _combined_string_field(packages: list[ScenarioPackage], field_name: str) -> list[str]:
    values: list[str] = []
    seen: set[str] = set()
    for package in packages:
        raw_values = package.spec.get(field_name, [])
        if not isinstance(raw_values, list):
            continue
        for value in raw_values:
            if isinstance(value, str) and value not in seen:
                values.append(value)
                seen.add(value)
    return values


def _combined_success_criteria(packages: list[ScenarioPackage]) -> dict[str, Any]:
    criteria_by_scenario = {
        package.name: copy.deepcopy(package.spec.get("success_criteria", {}))
        for package in packages
        if isinstance(package.spec.get("success_criteria"), dict)
    }
    requires_abstention = any(
        bool(criteria.get("requires_action_abstention"))
        for criteria in criteria_by_scenario.values()
        if isinstance(criteria, dict)
    )
    return {
        "requires_action_abstention": requires_abstention,
        "components": criteria_by_scenario,
    }


def _combined_scenario_name(packages: list[ScenarioPackage]) -> str:
    if not packages:
        return "combinatorial-incident"
    return "combinatorial:" + "+".join(package.name for package in packages)


def _unique_strings(values: Any) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _string_or_none(value)
        if text and text not in seen:
            selected.append(text)
            seen.add(text)
    return selected


def _path_text(path: Path) -> str:
    return str(path.resolve())


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


def _split_lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]
