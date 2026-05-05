"""Live scenario runtime helpers: seeding, waiting, selectors, and forwards."""

from __future__ import annotations

import os
import json
import re
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping, Protocol
from urllib.parse import urlparse

from . import parsers
from .port_forward import ForwardedPort, PortForwardError, PortForwardManager
from .progress import NoopProgressReporter
from .provider_contracts import ProviderProfile


CommandRunner = Callable[..., subprocess.CompletedProcess]
Clock = Callable[[], float]
Sleep = Callable[[float], None]

REPO_ROOT = Path(__file__).resolve().parents[1]
LINUX_VM_COMPOSE_FILE = REPO_ROOT / "harness/archetypes/linux-vm/docker-compose.yaml"
LINUX_VM_FAULTS_FILE = REPO_ROOT / "harness/shared/linux-faults.sh"
LINUX_VM_TARGET_SERVICE = "linux-target"
DNS_PROBE_LOOKUP_SCRIPT = REPO_ROOT / "harness/dns-probe/lookup.sh"
TLS_TARGET_CHECK_SCRIPT = REPO_ROOT / "harness/tls-target/check-tls.sh"
MESSAGING_STATE_READ_SCRIPT = REPO_ROOT / "harness/messaging-state-shell/read-evidence.sh"


@dataclass(frozen=True)
class SeedResult:
    failures: list[dict[str, str]] = field(default_factory=list)
    applied: bool = False


class SeedAdapter(Protocol):
    name: str

    def apply(self, package: Any, ctx: Any) -> SeedResult:
        ...

    def teardown(self, package: Any, ctx: Any) -> None:
        ...


class KindSeedAdapter:
    name = "kind"

    def __init__(self, command_runner: CommandRunner | None = None) -> None:
        self.command_runner = command_runner or _run_subprocess

    def apply(self, package: Any, ctx: Any) -> SeedResult:
        seed_yaml = package.seed_path / "seed.yaml"
        seed_sh = package.seed_path / "seed.sh"
        applied = False
        if seed_yaml.is_file():
            completed = self.command_runner(["kubectl", "apply", "-f", _absolute(seed_yaml)], env=ctx.host_env, cwd=package.path)
            if completed.returncode != 0:
                return SeedResult(
                    failures=[{"check": "seed_yaml_apply", "error": _command_error(completed, "kubectl apply failed")}],
                    applied=applied,
                )
            applied = True
        if _is_executable(seed_sh):
            completed = self.command_runner([_absolute(seed_sh)], env=ctx.host_env, cwd=package.path)
            if completed.returncode != 0:
                return SeedResult(
                    failures=[{"check": "seed_sh", "error": _command_error(completed, "seed.sh failed")}],
                    applied=applied,
                )
            applied = True
        return SeedResult(applied=applied)

    def teardown(self, package: Any, ctx: Any) -> None:
        teardown_sh = package.seed_path / "teardown.sh"
        seed_yaml = package.seed_path / "seed.yaml"
        if _is_executable(teardown_sh):
            self.command_runner([_absolute(teardown_sh)], env=ctx.host_env, cwd=package.path)
        elif seed_yaml.is_file():
            self.command_runner(
                ["kubectl", "delete", "-f", _absolute(seed_yaml), "--ignore-not-found"],
                env=ctx.host_env,
                cwd=package.path,
            )


class LinuxVMSeedAdapter:
    name = "linux-vm"

    def __init__(self, command_runner: CommandRunner | None = None) -> None:
        self.command_runner = command_runner or _run_subprocess

    def apply(self, package: Any, ctx: Any) -> SeedResult:
        seed_sh = package.seed_path / "seed.sh"
        if not _is_executable(seed_sh):
            return SeedResult()
        try:
            failure = _linux_vm_refresh_repo_files(ctx, self.command_runner, (LINUX_VM_FAULTS_FILE, seed_sh), cwd=package.path)
            if failure is not None:
                return SeedResult(failures=[failure])
            container_path = _container_repo_path(seed_sh)
        except ValueError as exc:
            return SeedResult(failures=[{"check": "seed_sh", "error": str(exc)}])
        completed = self.command_runner(_linux_vm_exec_args(ctx, ["bash", container_path]), env=ctx.host_env, cwd=package.path)
        if completed.returncode != 0:
            return SeedResult(failures=[{"check": "seed_sh", "error": _command_error(completed, "seed.sh failed")}])
        return SeedResult(applied=True)

    def teardown(self, package: Any, ctx: Any) -> None:
        teardown_sh = package.seed_path / "teardown.sh"
        files = [LINUX_VM_FAULTS_FILE]
        if _is_executable(teardown_sh):
            files.append(teardown_sh)
        _linux_vm_refresh_repo_files(ctx, self.command_runner, tuple(files), cwd=package.path)
        if _is_executable(teardown_sh):
            try:
                container_path = _container_repo_path(teardown_sh)
            except ValueError:
                return
            self.command_runner(_linux_vm_exec_args(ctx, ["bash", container_path]), env=ctx.host_env, cwd=package.path)
        else:
            self.command_runner(
                _linux_vm_exec_args(ctx, ["bash", "-lc", "source /sre-agent/harness/shared/linux-faults.sh; fault::cleanup_all"]),
                env=ctx.host_env,
                cwd=package.path,
            )


class StubSeedAdapter:
    def __init__(self, name: str, error: str) -> None:
        self.name = name
        self.error = error

    def apply(self, package: Any, ctx: Any) -> SeedResult:
        del package, ctx
        return SeedResult(failures=[{"check": f"{self.name}_seed", "error": self.error}])

    def teardown(self, package: Any, ctx: Any) -> None:
        del package, ctx


class SeedExecutor:
    def __init__(self, adapters: Mapping[str, SeedAdapter] | None = None) -> None:
        self.adapters = dict(adapters or default_seed_adapters())

    def apply(self, package: Any, ctx: Any) -> SeedResult:
        adapter = self.adapters.get(ctx.archetype)
        if adapter is None:
            return SeedResult()
        return adapter.apply(package, ctx)

    def teardown(self, package: Any, ctx: Any) -> None:
        adapter = self.adapters.get(ctx.archetype)
        if adapter is not None:
            adapter.teardown(package, ctx)


@dataclass(frozen=True)
class SelectorResolutionResult:
    inputs: dict[str, Any]
    failures: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class SelectorResolver(Protocol):
    kind: str
    target_input: str
    cardinality: str

    def resolve(self, value: str, inputs: dict[str, Any], ctx: Any) -> list[str]:
        ...


class PodLabelSelectorResolver:
    kind = "pod_label_selector"
    target_input = "pod"
    cardinality = "exactly_one"

    def __init__(self, command_runner: CommandRunner | None = None) -> None:
        self.resolver = KubernetesLabelSelectorResolver(
            kind=self.kind,
            target_input=self.target_input,
            resource="pod",
            command_runner=command_runner,
        )

    def resolve(self, value: str, inputs: dict[str, Any], ctx: Any) -> list[str]:
        return self.resolver.resolve(value, inputs, ctx)


class KubernetesLabelSelectorResolver:
    cardinality = "exactly_one"

    def __init__(
        self,
        *,
        kind: str,
        target_input: str,
        resource: str,
        command_runner: CommandRunner | None = None,
        namespaced: bool = True,
        cardinality: str = "exactly_one",
    ) -> None:
        self.kind = kind
        self.target_input = target_input
        self.resource = resource
        self.namespaced = namespaced
        self.cardinality = cardinality
        self.command_runner = command_runner or _run_subprocess

    def resolve(self, value: str, inputs: dict[str, Any], ctx: Any) -> list[str]:
        args = ["kubectl"]
        if self.namespaced:
            namespace = str(inputs.get("namespace") or "")
            if not namespace:
                raise ValueError(f"namespace is required to resolve {self.kind}")
            args.extend(["-n", namespace])
        args.extend(["get", self.resource, "-l", value, "-o", "jsonpath={.items[*].metadata.name}"])
        completed = self.command_runner(args, env=ctx.host_env)
        if completed.returncode != 0:
            raise ValueError(_command_error(completed, f"kubectl {self.kind} lookup failed"))
        return _split_names(completed.stdout)


class NodeLabelSelectorResolver(KubernetesLabelSelectorResolver):
    def __init__(self, command_runner: CommandRunner | None = None) -> None:
        super().__init__(
            kind="node_label_selector",
            target_input="node",
            resource="node",
            command_runner=command_runner,
            namespaced=False,
        )


class PodLabelSelectorListResolver(KubernetesLabelSelectorResolver):
    def __init__(self, command_runner: CommandRunner | None = None) -> None:
        super().__init__(
            kind="pod_label_selector_list",
            target_input="pods",
            resource="pod",
            command_runner=command_runner,
            cardinality="list",
        )


class KubernetesNamedResourceSelectorResolver(KubernetesLabelSelectorResolver):
    def __init__(
        self,
        *,
        kind: str,
        target_input: str,
        resource: str,
        command_runner: CommandRunner | None = None,
    ) -> None:
        super().__init__(
            kind=kind,
            target_input=target_input,
            resource=resource,
            command_runner=command_runner,
        )


class LegacyPodLabelSelectorResolver:
    """Compatibility wrapper retained for older imports."""

    kind = "pod_label_selector"
    target_input = "pod"
    cardinality = "exactly_one"

    def __init__(self, command_runner: CommandRunner | None = None) -> None:
        self.command_runner = command_runner or _run_subprocess

    def resolve(self, value: str, inputs: dict[str, Any], ctx: Any) -> list[str]:
        namespace = str(inputs.get("namespace") or "")
        if not namespace:
            raise ValueError("namespace is required to resolve pod_label_selector")
        completed = self.command_runner(
            ["kubectl", "-n", namespace, "get", "pod", "-l", value, "-o", "jsonpath={.items[*].metadata.name}"],
            env=ctx.host_env,
        )
        if completed.returncode != 0:
            raise ValueError(_command_error(completed, "kubectl pod selector lookup failed"))
        return _split_names(completed.stdout)


class NotImplementedSelectorResolver:
    cardinality = "exactly_one"

    def __init__(self, kind: str, target_input: str) -> None:
        self.kind = kind
        self.target_input = target_input

    def resolve(self, value: str, inputs: dict[str, Any], ctx: Any) -> list[str]:
        del value, inputs, ctx
        raise NotImplementedError(f"{self.kind} selector resolution is not implemented yet")


def resolve_selectors(
    package: Any,
    ctx: Any,
    *,
    inputs: Mapping[str, Any] | None = None,
    fixture_mode: bool = False,
    resolvers: Mapping[str, SelectorResolver] | None = None,
) -> SelectorResolutionResult:
    resolved_inputs = dict(inputs or package.spec.get("inputs", {}))
    if fixture_mode:
        return SelectorResolutionResult(inputs=resolved_inputs)
    registry = dict(resolvers or default_selector_resolvers())
    metadata: dict[str, Any] = {}
    failures: list[dict[str, Any]] = []
    for key, value in list(resolved_inputs.items()):
        resolver = registry.get(key)
        if resolver is None:
            continue
        try:
            matches = resolver.resolve(str(value), resolved_inputs, ctx)
        except (NotImplementedError, ValueError) as exc:
            failures.append({"check": key, "error": str(exc)})
            continue
        selected, failure = _select_by_cardinality(key, resolver.cardinality, matches)
        if failure is not None:
            failures.append(failure)
            continue
        resolved_inputs[resolver.target_input] = selected
        metadata[key] = {"target_input": resolver.target_input, "resolved": selected, "matches": matches}
    return SelectorResolutionResult(inputs=resolved_inputs, failures=failures, metadata=metadata)


@dataclass(frozen=True)
class PredicateResult:
    matched: bool
    observed: Any


class Predicate(Protocol):
    kind: str
    archetypes: tuple[str, ...]

    def evaluate(self, params: dict[str, Any], ctx: Any, inputs: dict[str, Any]) -> PredicateResult:
        ...


class PodPhasePredicate:
    kind = "pod_phase"
    archetypes = ("kind",)

    def __init__(self, command_runner: CommandRunner | None = None) -> None:
        self.command_runner = command_runner or _run_subprocess

    def evaluate(self, params: dict[str, Any], ctx: Any, inputs: dict[str, Any]) -> PredicateResult:
        namespace = str(params.get("namespace") or inputs.get("namespace") or "")
        selector = str(params.get("label_selector") or inputs.get("pod_label_selector") or "")
        phase = str(params.get("phase") or "")
        completed = self.command_runner(
            ["kubectl", "-n", namespace, "get", "pod", "-l", selector, "-o", "jsonpath={.items[*].status.phase}"],
            env=ctx.host_env,
        )
        observed = _command_error(completed, "") if completed.returncode != 0 else _split_names(completed.stdout)
        return PredicateResult(matched=phase in observed if isinstance(observed, list) else False, observed=observed)


class PodEventReasonPredicate:
    kind = "pod_event_reason"
    archetypes = ("kind",)

    def __init__(self, command_runner: CommandRunner | None = None) -> None:
        self.command_runner = command_runner or _run_subprocess

    def evaluate(self, params: dict[str, Any], ctx: Any, inputs: dict[str, Any]) -> PredicateResult:
        namespace = str(params.get("namespace") or inputs.get("namespace") or "")
        selector = str(params.get("label_selector") or inputs.get("pod_label_selector") or "")
        reason = str(params.get("reason") or "")
        pod_lookup = self.command_runner(
            ["kubectl", "-n", namespace, "get", "pod", "-l", selector, "-o", "jsonpath={.items[*].metadata.name}"],
            env=ctx.host_env,
        )
        if pod_lookup.returncode != 0:
            observed = _command_error(pod_lookup, "pod selector lookup failed")
            return PredicateResult(matched=False, observed=observed)
        observed_reasons: list[str] = []
        for pod in _split_names(pod_lookup.stdout):
            completed = self.command_runner(
                [
                    "kubectl",
                    "-n",
                    namespace,
                    "get",
                    "events",
                    "--field-selector",
                    f"involvedObject.name={pod}",
                    "-o",
                    "jsonpath={.items[*].reason}",
                ],
                env=ctx.host_env,
            )
            if completed.returncode == 0:
                observed_reasons.extend(_split_names(completed.stdout))
            else:
                observed_reasons.append(_command_error(completed, "event lookup failed"))
        return PredicateResult(matched=reason in observed_reasons, observed=observed_reasons)


class PodConditionPredicate:
    kind = "pod_condition"
    archetypes = ("kind",)

    def __init__(self, command_runner: CommandRunner | None = None) -> None:
        self.command_runner = command_runner or _run_subprocess

    def evaluate(self, params: dict[str, Any], ctx: Any, inputs: dict[str, Any]) -> PredicateResult:
        namespace = str(params.get("namespace") or inputs.get("namespace") or "")
        selector = str(params.get("label_selector") or inputs.get("pod_label_selector") or "")
        condition = str(params.get("condition") or "")
        status = str(params.get("status") or "True")
        completed = self.command_runner(
            [
                "kubectl",
                "-n",
                namespace,
                "get",
                "pod",
                "-l",
                selector,
                "-o",
                f"jsonpath={{.items[*].status.conditions[?(@.type==\"{condition}\")].status}}",
            ],
            env=ctx.host_env,
        )
        observed = _command_error(completed, "") if completed.returncode != 0 else _split_names(completed.stdout)
        return PredicateResult(matched=status in observed if isinstance(observed, list) else False, observed=observed)


class PodRestartCountMinPredicate:
    kind = "pod_restart_count_min"
    archetypes = ("kind",)

    def __init__(self, command_runner: CommandRunner | None = None) -> None:
        self.command_runner = command_runner or _run_subprocess

    def evaluate(self, params: dict[str, Any], ctx: Any, inputs: dict[str, Any]) -> PredicateResult:
        namespace = str(params.get("namespace") or inputs.get("namespace") or "")
        selector = str(params.get("label_selector") or inputs.get("pod_label_selector") or "")
        minimum = int(params.get("min") or 1)
        completed = self.command_runner(
            [
                "kubectl",
                "-n",
                namespace,
                "get",
                "pod",
                "-l",
                selector,
                "-o",
                "jsonpath={.items[*].status.containerStatuses[*].restartCount}",
            ],
            env=ctx.host_env,
        )
        observed = _command_error(completed, "") if completed.returncode != 0 else _parse_ints(completed.stdout)
        return PredicateResult(matched=max(observed or [0]) >= minimum if isinstance(observed, list) else False, observed=observed)


class DeploymentReplicasReadyPredicate:
    kind = "deployment_replicas_ready"
    archetypes = ("kind",)

    def __init__(self, command_runner: CommandRunner | None = None) -> None:
        self.command_runner = command_runner or _run_subprocess

    def evaluate(self, params: dict[str, Any], ctx: Any, inputs: dict[str, Any]) -> PredicateResult:
        namespace = str(params.get("namespace") or inputs.get("namespace") or "")
        minimum = int(params.get("min") or 1)
        args = ["kubectl", "-n", namespace, "get", "deployment"]
        if params.get("name"):
            args.append(str(params["name"]))
            jsonpath = "jsonpath={.status.readyReplicas}"
        else:
            selector = str(params.get("label_selector") or inputs.get("deployment_label_selector") or "")
            args.extend(["-l", selector])
            jsonpath = "jsonpath={.items[*].status.readyReplicas}"
        args.extend(["-o", jsonpath])
        completed = self.command_runner(args, env=ctx.host_env)
        observed = _command_error(completed, "") if completed.returncode != 0 else _parse_ints(completed.stdout)
        return PredicateResult(matched=max(observed or [0]) >= minimum if isinstance(observed, list) else False, observed=observed)


class NodeConditionPredicate:
    kind = "node_condition"
    archetypes = ("kind",)

    def __init__(self, command_runner: CommandRunner | None = None) -> None:
        self.command_runner = command_runner or _run_subprocess

    def evaluate(self, params: dict[str, Any], ctx: Any, inputs: dict[str, Any]) -> PredicateResult:
        condition = str(params.get("condition") or "")
        status = str(params.get("status") or "True")
        args = ["kubectl", "get", "node"]
        if params.get("name") or inputs.get("node"):
            args.append(str(params.get("name") or inputs.get("node")))
            jsonpath = f"jsonpath={{.status.conditions[?(@.type==\"{condition}\")].status}}"
        else:
            selector = str(params.get("label_selector") or inputs.get("node_label_selector") or "")
            args.extend(["-l", selector])
            jsonpath = f"jsonpath={{.items[*].status.conditions[?(@.type==\"{condition}\")].status}}"
        args.extend(["-o", jsonpath])
        completed = self.command_runner(args, env=ctx.host_env)
        observed = _command_error(completed, "") if completed.returncode != 0 else _split_names(completed.stdout)
        return PredicateResult(matched=status in observed if isinstance(observed, list) else False, observed=observed)


class PvcPhasePredicate:
    kind = "pvc_phase"
    archetypes = ("kind",)

    def __init__(self, command_runner: CommandRunner | None = None) -> None:
        self.command_runner = command_runner or _run_subprocess

    def evaluate(self, params: dict[str, Any], ctx: Any, inputs: dict[str, Any]) -> PredicateResult:
        namespace = str(params.get("namespace") or inputs.get("namespace") or "")
        phase = str(params.get("phase") or "")
        args = ["kubectl", "-n", namespace, "get", "pvc"]
        if params.get("name") or inputs.get("pvc"):
            args.append(str(params.get("name") or inputs.get("pvc")))
            jsonpath = "jsonpath={.status.phase}"
        else:
            selector = str(params.get("label_selector") or inputs.get("pvc_label_selector") or "")
            args.extend(["-l", selector])
            jsonpath = "jsonpath={.items[*].status.phase}"
        args.extend(["-o", jsonpath])
        completed = self.command_runner(args, env=ctx.host_env)
        observed = _command_error(completed, "") if completed.returncode != 0 else _split_names(completed.stdout)
        return PredicateResult(matched=phase in observed if isinstance(observed, list) else False, observed=observed)


class PrometheusQueryThresholdPredicate:
    kind = "prometheus_query_threshold"
    archetypes = ("kind",)

    def __init__(self, command_runner: CommandRunner | None = None) -> None:
        self.command_runner = command_runner or _run_subprocess

    def evaluate(self, params: dict[str, Any], ctx: Any, inputs: dict[str, Any]) -> PredicateResult:
        del inputs
        query = str(params.get("query") or "")
        base_url = str(params.get("url") or ctx.host_env.get("PROMETHEUS_URL") or ctx.host_env.get("SRE_AGENT_PROMETHEUS_URL") or "")
        comparator = str(params.get("comparator") or "gte")
        threshold = float(params.get("threshold") or 0)
        if not base_url:
            return PredicateResult(matched=False, observed="PROMETHEUS_URL is required")
        completed = self.command_runner(
            ["curl", "-fsS", "--get", f"{base_url.rstrip('/')}/api/v1/query", "--data-urlencode", f"query={query}"],
            env=ctx.host_env,
        )
        if completed.returncode != 0:
            return PredicateResult(matched=False, observed=_command_error(completed, "prometheus query failed"))
        values = _prometheus_values(completed.stdout)
        return PredicateResult(matched=any(_compare(value, comparator, threshold) for value in values), observed=values)


class PostgresConnectionCountMinPredicate:
    kind = "postgres_connection_count_min"
    archetypes = ("kind",)

    def __init__(self, command_runner: CommandRunner | None = None) -> None:
        self.command_runner = command_runner or _run_subprocess

    def evaluate(self, params: dict[str, Any], ctx: Any, inputs: dict[str, Any]) -> PredicateResult:
        del inputs
        database = str(params.get("database") or "")
        minimum = float(params.get("min") or params.get("min_count") or 0)
        base_url = str(params.get("url") or ctx.host_env.get("PROMETHEUS_URL") or ctx.host_env.get("SRE_AGENT_PROMETHEUS_URL") or "")
        if not database:
            return PredicateResult(matched=False, observed="database is required")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,127}", database):
            return PredicateResult(matched=False, observed="database contains unsafe characters")
        if not base_url:
            return PredicateResult(matched=False, observed="PROMETHEUS_URL is required")
        query = f'sum(pg_stat_database_numbackends{{datname="{database}"}})'
        completed = self.command_runner(
            ["curl", "-fsS", "--get", f"{base_url.rstrip('/')}/api/v1/query", "--data-urlencode", f"query={query}"],
            env=ctx.host_env,
        )
        if completed.returncode != 0:
            return PredicateResult(matched=False, observed=_command_error(completed, "postgres connection query failed"))
        values = _prometheus_values(completed.stdout)
        observed = max(values) if values else 0.0
        return PredicateResult(matched=observed >= minimum, observed={"database": database, "connection_count": observed})


class LokiLogMatchPredicate:
    kind = "loki_log_match"
    archetypes = ("kind",)

    def __init__(self, command_runner: CommandRunner | None = None) -> None:
        self.command_runner = command_runner or _run_subprocess

    def evaluate(self, params: dict[str, Any], ctx: Any, inputs: dict[str, Any]) -> PredicateResult:
        del inputs
        query = str(params.get("query") or "")
        base_url = str(params.get("url") or ctx.host_env.get("LOKI_URL") or ctx.host_env.get("SRE_AGENT_LOKI_URL") or "")
        minimum = int(params.get("min_lines") or 1)
        if not base_url:
            return PredicateResult(matched=False, observed="LOKI_URL is required")
        completed = self.command_runner(
            ["curl", "-fsS", "--get", f"{base_url.rstrip('/')}/loki/api/v1/query_range", "--data-urlencode", f"query={query}"],
            env=ctx.host_env,
        )
        if completed.returncode != 0:
            return PredicateResult(matched=False, observed=_command_error(completed, "loki query failed"))
        line_count = _loki_line_count(completed.stdout)
        return PredicateResult(matched=line_count >= minimum, observed={"line_count": line_count})


class HttpEndpointStatusPredicate:
    kind = "http_endpoint_status"
    archetypes = ("kind", "linux-vm")

    def __init__(self, command_runner: CommandRunner | None = None) -> None:
        self.command_runner = command_runner or _run_subprocess

    def evaluate(self, params: dict[str, Any], ctx: Any, inputs: dict[str, Any]) -> PredicateResult:
        del inputs
        url = str(params.get("url") or "")
        expected_status = int(params.get("expected_status") or 200)
        completed = self.command_runner(["curl", "-sS", "-o", "/dev/null", "-w", "%{http_code}", url], env=ctx.host_env)
        observed = _command_error(completed, "") if completed.returncode != 0 else (completed.stdout or "").strip()
        return PredicateResult(matched=str(expected_status) == str(observed), observed=observed)


class LinuxDiskUsageMinPredicate:
    kind = "linux_disk_usage_min"
    archetypes = ("linux-vm",)

    def __init__(self, command_runner: CommandRunner | None = None) -> None:
        self.command_runner = command_runner or _run_subprocess

    def evaluate(self, params: dict[str, Any], ctx: Any, inputs: dict[str, Any]) -> PredicateResult:
        del inputs
        mount = str(params.get("mount") or "/")
        minimum = float(params.get("min_percent") or 0)
        completed = self.command_runner(_linux_vm_exec_args(ctx, ["df", "-P", mount]), env=ctx.host_env)
        if completed.returncode != 0:
            return PredicateResult(matched=False, observed={"mount": mount, "error": _command_error(completed, "df failed")})
        usage = _df_usage_percent(completed.stdout)
        observed: dict[str, Any] = {"mount": mount, "percent": usage}
        if usage is None:
            observed["raw"] = completed.stdout
        return PredicateResult(matched=usage >= minimum if usage is not None else False, observed=observed)


class LinuxInodeUsageMinPredicate:
    kind = "linux_inode_usage_min"
    archetypes = ("linux-vm",)

    def __init__(self, command_runner: CommandRunner | None = None) -> None:
        self.command_runner = command_runner or _run_subprocess

    def evaluate(self, params: dict[str, Any], ctx: Any, inputs: dict[str, Any]) -> PredicateResult:
        del inputs
        mount = str(params.get("mount") or "/")
        minimum = float(params.get("min_percent") or 0)
        completed = self.command_runner(_linux_vm_exec_args(ctx, ["df", "-Pi", mount]), env=ctx.host_env)
        if completed.returncode != 0:
            return PredicateResult(matched=False, observed={"mount": mount, "error": _command_error(completed, "df -Pi failed")})
        usage = _df_usage_percent(completed.stdout)
        observed: dict[str, Any] = {"mount": mount, "percent": usage}
        if usage is None:
            observed["raw"] = completed.stdout
        return PredicateResult(matched=usage >= minimum if usage is not None else False, observed=observed)


class LinuxDeletedOpenFilesMinPredicate:
    kind = "linux_deleted_open_files_min"
    archetypes = ("linux-vm",)

    def __init__(self, command_runner: CommandRunner | None = None) -> None:
        self.command_runner = command_runner or _run_subprocess

    def evaluate(self, params: dict[str, Any], ctx: Any, inputs: dict[str, Any]) -> PredicateResult:
        del inputs
        mount = str(params.get("mount") or "/")
        minimum = int(params.get("min_count") or 1)
        completed = self.command_runner(_linux_vm_exec_args(ctx, ["lsof", "+L1", mount]), env=ctx.host_env)
        if completed.returncode not in (0, 1):
            return PredicateResult(matched=False, observed={"mount": mount, "error": _command_error(completed, "lsof failed")})
        count = _deleted_open_file_count(completed.stdout)
        return PredicateResult(matched=count >= minimum, observed={"mount": mount, "count": count})


class LinuxLoadAvgMinPredicate:
    kind = "linux_load_avg_min"
    archetypes = ("linux-vm",)

    def __init__(self, command_runner: CommandRunner | None = None) -> None:
        self.command_runner = command_runner or _run_subprocess

    def evaluate(self, params: dict[str, Any], ctx: Any, inputs: dict[str, Any]) -> PredicateResult:
        del inputs
        minimum = float(params.get("min") or 0)
        completed = self.command_runner(_linux_vm_exec_args(ctx, ["cat", "/proc/loadavg"]), env=ctx.host_env)
        if completed.returncode != 0:
            return PredicateResult(matched=False, observed={"error": _command_error(completed, "loadavg read failed")})
        value = _first_float(completed.stdout)
        observed: dict[str, Any] = {"load_1m": value}
        if value is None:
            observed["raw"] = completed.stdout
        return PredicateResult(matched=value >= minimum if value is not None else False, observed=observed)


class LinuxCpuUsageMinPredicate:
    kind = "linux_cpu_usage_min"
    archetypes = ("linux-vm",)

    def __init__(self, command_runner: CommandRunner | None = None) -> None:
        self.command_runner = command_runner or _run_subprocess

    def evaluate(self, params: dict[str, Any], ctx: Any, inputs: dict[str, Any]) -> PredicateResult:
        del inputs
        minimum = float(params.get("min_percent") or 0)
        completed = self.command_runner(_linux_vm_exec_args(ctx, ["mpstat", "1", "1"]), env=ctx.host_env)
        if completed.returncode != 0:
            return PredicateResult(matched=False, observed={"error": _command_error(completed, "mpstat failed")})
        used = _mpstat_used_percent(completed.stdout)
        observed: dict[str, Any] = {"used_percent": used}
        if used is None:
            observed["raw"] = completed.stdout
        return PredicateResult(matched=used >= minimum if used is not None else False, observed=observed)


class LinuxMemoryUsageMinPredicate:
    kind = "linux_memory_usage_min"
    archetypes = ("linux-vm",)

    def __init__(self, command_runner: CommandRunner | None = None) -> None:
        self.command_runner = command_runner or _run_subprocess

    def evaluate(self, params: dict[str, Any], ctx: Any, inputs: dict[str, Any]) -> PredicateResult:
        del inputs
        minimum = float(params.get("min_percent") or 0)
        completed = self.command_runner(
            _linux_vm_exec_args(ctx, ["bash", "-lc", "source /sre-agent/harness/shared/linux-faults.sh; fault::print_memory_summary"]),
            env=ctx.host_env,
        )
        if completed.returncode != 0:
            return PredicateResult(matched=False, observed={"error": _command_error(completed, "memory summary failed")})
        used = _free_used_percent(completed.stdout)
        observed: dict[str, Any] = {"used_percent": used}
        if used is None:
            observed["raw"] = completed.stdout
        return PredicateResult(matched=used >= minimum if used is not None else False, observed=observed)


class LinuxOomEventsMinPredicate:
    kind = "linux_oom_events_min"
    archetypes = ("linux-vm",)

    def __init__(self, command_runner: CommandRunner | None = None) -> None:
        self.command_runner = command_runner or _run_subprocess

    def evaluate(self, params: dict[str, Any], ctx: Any, inputs: dict[str, Any]) -> PredicateResult:
        del inputs
        minimum = int(params.get("min_count") or 0)
        completed = self.command_runner(
            _linux_vm_exec_args(ctx, ["bash", "-lc", "source /sre-agent/harness/shared/linux-faults.sh; fault::print_oom_events"]),
            env=ctx.host_env,
        )
        if completed.returncode != 0:
            return PredicateResult(matched=False, observed={"error": _command_error(completed, "oom events failed")})
        count = _oom_event_count(completed.stdout)
        observed = {"count": count, "entries": [line.strip() for line in completed.stdout.splitlines() if line.strip()][:10]}
        return PredicateResult(matched=count >= minimum, observed=observed)


class ChaosMeshPhasePredicate:
    kind = "chaos_mesh_phase"
    archetypes = ("kind",)

    def __init__(self, command_runner: CommandRunner | None = None) -> None:
        self.command_runner = command_runner or _run_subprocess

    def evaluate(self, params: dict[str, Any], ctx: Any, inputs: dict[str, Any]) -> PredicateResult:
        namespace = str(params.get("namespace") or inputs.get("namespace") or "default")
        resource_kind = str(params.get("resource_kind") or params.get("kind_name") or params.get("chaos_kind") or "")
        name = str(params.get("name") or "")
        phase = str(params.get("phase") or "Running")
        observed = ""
        error = ""
        for jsonpath in ("jsonpath={.status.phase}", "jsonpath={.status.experiment.desiredPhase}"):
            completed = self.command_runner(
                ["kubectl", "-n", namespace, "get", resource_kind, name, "-o", jsonpath],
                env=ctx.host_env,
            )
            if completed.returncode != 0:
                error = _command_error(completed, "")
                continue
            observed = (completed.stdout or "").strip()
            if observed:
                break
        if not observed and error:
            observed = error
        return PredicateResult(matched=_chaos_phase_matches(observed, phase), observed=observed)


class TlsCertificateInvalidPredicate:
    kind = "tls_certificate_invalid"
    archetypes = ("kind",)

    def __init__(self, command_runner: CommandRunner | None = None) -> None:
        self.command_runner = command_runner or _run_subprocess

    def evaluate(self, params: dict[str, Any], ctx: Any, inputs: dict[str, Any]) -> PredicateResult:
        hostname = str(params.get("hostname") or inputs.get("hostname") or inputs.get("host") or "")
        namespace = str(params.get("namespace") or inputs.get("namespace") or "default")
        service = str(params.get("service") or inputs.get("service") or "")
        probe = str(params.get("dns_tls_probe") or inputs.get("dns_tls_probe") or "sre-agent-dns-tls-probe")
        if not hostname or not service:
            return PredicateResult(matched=False, observed={"error": "hostname and service are required"})
        completed = self.command_runner([str(TLS_TARGET_CHECK_SCRIPT), hostname, namespace, service, probe], env=ctx.host_env)
        if completed.returncode != 0:
            return PredicateResult(
                matched=False,
                observed=_tls_failure_observation(
                    completed,
                    namespace=namespace,
                    service=service,
                    hostname=hostname,
                    probe=probe,
                    ctx=ctx,
                    command_runner=self.command_runner,
                ),
            )
        observed = parsers.parse_tls_check(completed.stdout)
        reason = str(params.get("reason") or params.get("expected_reason") or "invalid").lower().replace("-", "_")
        days_remaining = observed.get("days_remaining")
        valid = observed.get("valid")
        hostname_match = observed.get("hostname_match")
        if reason in {"expiring", "certificate_expiring", "certificate_rotation_needed", "near_expiry"}:
            max_days = int(params.get("max_days_remaining") or 7)
            matched = valid is True and isinstance(days_remaining, int) and days_remaining <= max_days
        elif reason in {"expired", "certificate_expired"}:
            matched = valid is False and isinstance(days_remaining, int) and days_remaining < 0
        elif reason in {"hostname_mismatch", "certificate_hostname_mismatch"}:
            matched = valid is False and hostname_match is False
        else:
            matched = valid is False
        return PredicateResult(matched=matched, observed=observed)


class DnsResolutionFailsPredicate:
    kind = "dns_resolution_fails"
    archetypes = ("kind",)

    def __init__(self, command_runner: CommandRunner | None = None) -> None:
        self.command_runner = command_runner or _run_subprocess

    def evaluate(self, params: dict[str, Any], ctx: Any, inputs: dict[str, Any]) -> PredicateResult:
        hostname = str(params.get("hostname") or inputs.get("hostname") or inputs.get("host") or "")
        namespace = str(params.get("namespace") or inputs.get("namespace") or "default")
        probe = str(params.get("dns_tls_probe") or inputs.get("dns_tls_probe") or "sre-agent-dns-tls-probe")
        expected_status = str(params.get("status") or "nxdomain").lower()
        if not hostname:
            return PredicateResult(matched=False, observed={"error": "hostname is required"})
        completed = self.command_runner([str(DNS_PROBE_LOOKUP_SCRIPT), hostname, namespace, probe], env=ctx.host_env)
        if completed.returncode != 0:
            return PredicateResult(matched=False, observed={"error": _command_error(completed, "dns lookup failed")})
        observed = parsers.parse_dns_lookup(completed.stdout)
        return PredicateResult(matched=str(observed.get("status", "")).lower() == expected_status, observed=observed)


class KafkaConsumerLagMinPredicate:
    kind = "kafka_consumer_lag_min"
    archetypes = ("kind",)

    def __init__(self, command_runner: CommandRunner | None = None) -> None:
        self.command_runner = command_runner or _run_subprocess

    def evaluate(self, params: dict[str, Any], ctx: Any, inputs: dict[str, Any]) -> PredicateResult:
        completed = self.command_runner(_messaging_state_args(params, inputs, "queue_consumer_lag.txt"), env=ctx.host_env)
        if completed.returncode != 0:
            return PredicateResult(matched=False, observed={"error": _command_error(completed, "queue lag lookup failed")})
        observed = parsers.parse_queue_consumer_lag(completed.stdout)
        checks = [
            _numeric_check(observed.get("total_lag"), "gte", params.get("min") or params.get("min_total_lag")),
            _numeric_check(observed.get("oldest_message_age_seconds"), "gte", params.get("min_oldest_message_age_seconds")),
            _numeric_check(observed.get("max_partition_lag"), "gte", params.get("min_max_partition_lag")),
            _numeric_check(observed.get("active_consumers"), "lte", params.get("max_active_consumers")),
        ]
        active_equals_expected = params.get("active_consumers_equal_expected")
        if active_equals_expected is not None:
            checks.append(bool(active_equals_expected) == (observed.get("active_consumers") == observed.get("expected_consumers")))
        configured = [check for check in checks if check is not None]
        return PredicateResult(matched=bool(configured) and all(configured), observed=observed)


class KafkaPartitionRebalanceActivePredicate:
    kind = "kafka_partition_rebalance_active"
    archetypes = ("kind",)

    def __init__(self, command_runner: CommandRunner | None = None) -> None:
        self.command_runner = command_runner or _run_subprocess

    def evaluate(self, params: dict[str, Any], ctx: Any, inputs: dict[str, Any]) -> PredicateResult:
        completed = self.command_runner(_messaging_state_args(params, inputs, "kafka_group_state.txt"), env=ctx.host_env)
        if completed.returncode != 0:
            return PredicateResult(matched=False, observed={"error": _command_error(completed, "kafka group state lookup failed")})
        observed = parsers.parse_kafka_group_state(completed.stdout)
        expected_states = params.get("states") or params.get("state") or ["PreparingRebalance", "CompletingRebalance"]
        if isinstance(expected_states, str):
            expected_states = [expected_states]
        checks = [
            str(observed.get("state") or "") in {str(state) for state in expected_states},
            _numeric_check(observed.get("assignments_revoked"), "gte", params.get("min_assignments_revoked")),
            _numeric_check(observed.get("rebalance_age_seconds"), "gte", params.get("min_rebalance_age_seconds")),
            _numeric_check(observed.get("members"), "lte", params.get("max_members")),
        ]
        configured = [check for check in checks if check is not None]
        return PredicateResult(matched=bool(configured) and all(configured), observed=observed)


class QueueDeadLetterMinPredicate:
    kind = "queue_dead_letter_min"
    archetypes = ("kind",)

    def __init__(self, command_runner: CommandRunner | None = None) -> None:
        self.command_runner = command_runner or _run_subprocess

    def evaluate(self, params: dict[str, Any], ctx: Any, inputs: dict[str, Any]) -> PredicateResult:
        completed = self.command_runner(_messaging_state_args(params, inputs, "queue_dead_letter.txt"), env=ctx.host_env)
        if completed.returncode != 0:
            return PredicateResult(matched=False, observed={"error": _command_error(completed, "dead-letter lookup failed")})
        observed = parsers.parse_queue_dead_letter(completed.stdout)
        checks = [
            _numeric_check(observed.get("message_count"), "gte", params.get("min") or params.get("min_messages")),
            _numeric_check(observed.get("oldest_age_seconds"), "gte", params.get("min_oldest_age_seconds")),
        ]
        configured = [check for check in checks if check is not None]
        return PredicateResult(matched=bool(configured) and all(configured), observed=observed)


class NotImplementedPredicate:
    archetypes = ("kind", "linux-vm")

    def __init__(self, kind: str) -> None:
        self.kind = kind

    def evaluate(self, params: dict[str, Any], ctx: Any, inputs: dict[str, Any]) -> PredicateResult:
        del params, ctx, inputs
        return PredicateResult(matched=False, observed=f"{self.kind} predicate is not implemented yet")


@dataclass(frozen=True)
class WaitResult:
    failures: list[dict[str, Any]] = field(default_factory=list)
    matched: bool = True


class SymptomWaiter:
    def __init__(
        self,
        predicates: Mapping[str, Predicate] | None = None,
        *,
        sleep: Sleep = time.sleep,
        clock: Clock = time.monotonic,
        progress_reporter: Any | None = None,
    ) -> None:
        self.predicates = dict(predicates or default_predicates())
        self.sleep = sleep
        self.clock = clock
        self.progress_reporter = progress_reporter or NoopProgressReporter()

    def wait(self, package: Any, ctx: Any, inputs: Mapping[str, Any]) -> WaitResult:
        wait_for = package.wait_for
        if not wait_for:
            self.progress_reporter.emit("wait_for", "skipped", "scenario has no wait predicates")
            return WaitResult()
        timeout_seconds = float(wait_for.get("timeout_seconds", 90))
        interval_seconds = float(wait_for.get("interval_seconds", 2))
        predicate_specs = wait_for.get("predicates", [])
        if not isinstance(predicate_specs, list):
            failures = [{"check": "wait_for", "error": "wait_for.predicates must be a list"}]
            self.progress_reporter.emit("wait_for", "failed", "wait predicate contract is invalid", details={"failures": failures})
            return WaitResult(failures=failures, matched=False)
        resolved_inputs = dict(inputs)
        deadline = self.clock() + timeout_seconds
        last_results: list[tuple[dict[str, Any], PredicateResult]] = []
        self.progress_reporter.emit(
            "wait_for",
            "started",
            str(wait_for.get("description") or "waiting for symptoms"),
            details={
                "timeout_seconds": timeout_seconds,
                "interval_seconds": interval_seconds,
                "predicate_count": len(predicate_specs),
            },
        )
        while True:
            failures: list[dict[str, Any]] = []
            last_results = []
            for spec in predicate_specs:
                if not isinstance(spec, dict):
                    failures.append({"check": "wait_for", "error": "predicate must be a mapping"})
                    continue
                rendered = _render_templates(spec, resolved_inputs)
                kind = str(rendered.get("kind") or "")
                predicate = self.predicates.get(kind)
                if predicate is None:
                    failures.append({"check": kind or "wait_for", "error": f"unknown wait_for predicate kind: {kind!r}"})
                    continue
                if ctx.archetype not in predicate.archetypes:
                    failures.append({"check": kind, "error": f"{kind} does not support archetype {ctx.archetype}"})
                    continue
                result = predicate.evaluate(rendered, ctx, resolved_inputs)
                last_results.append((rendered, result))
                self.progress_reporter.emit(
                    "wait_for",
                    "observed",
                    f"{kind} {'matched' if result.matched else 'pending'}",
                    details={
                        "kind": kind,
                        "matched": result.matched,
                        "observed": result.observed,
                    },
                )
            if failures:
                self.progress_reporter.emit("wait_for", "failed", "wait predicate evaluation failed", details={"failures": failures})
                return WaitResult(failures=failures, matched=False)
            if last_results and all(result.matched for _spec, result in last_results):
                self.progress_reporter.emit(
                    "wait_for",
                    "ok",
                    "all wait predicates matched",
                    details={"predicate_count": len(last_results)},
                )
                return WaitResult()
            if self.clock() >= deadline:
                failures = _wait_timeout_failures(last_results)
                self.progress_reporter.emit("wait_for", "failed", "wait predicates timed out", details={"failures": failures})
                return WaitResult(failures=failures, matched=False)
            self.sleep(interval_seconds)


@dataclass(frozen=True)
class PortForwardRun:
    manager: PortForwardManager | None
    forwards: list[ForwardedPort]
    failures: list[dict[str, str]] = field(default_factory=list)

    def stop_all(self) -> None:
        if self.manager is not None:
            self.manager.stop_all()


def start_port_forwards(
    ctx: Any,
    profile: ProviderProfile | None,
    *,
    manager_factory: Callable[[str], PortForwardManager] | None = None,
) -> PortForwardRun:
    if profile is None or ctx.archetype != "kind":
        return PortForwardRun(manager=None, forwards=[])
    kubeconfig = str(ctx.host_env.get("SRE_AGENT_KIND_KUBECONFIG") or ctx.kubeconfig_path or "")
    if not kubeconfig:
        return PortForwardRun(
            manager=None,
            forwards=[],
            failures=[{"check": "port_forward", "error": "SRE_AGENT_KIND_KUBECONFIG is required for kind port-forwards"}],
        )
    forward_specs = _forward_specs_for_profile(profile)
    if not forward_specs:
        return PortForwardRun(manager=None, forwards=[])
    manager = manager_factory(kubeconfig) if manager_factory is not None else PortForwardManager(kubeconfig)
    forwards: list[ForwardedPort] = []
    for service, namespace, remote_port in forward_specs:
        try:
            forwards.append(manager.forward(service=service, namespace=namespace, remote_port=remote_port))
        except PortForwardError as exc:
            manager.stop_all()
            return PortForwardRun(
                manager=manager,
                forwards=forwards,
                failures=[{"check": f"port_forward:{namespace}/{service}", "error": str(exc)}],
            )
    return PortForwardRun(manager=manager, forwards=forwards)


def default_seed_adapters(command_runner: CommandRunner | None = None) -> dict[str, SeedAdapter]:
    return {
        "kind": KindSeedAdapter(command_runner),
        "linux-vm": LinuxVMSeedAdapter(command_runner),
        "eks-staging": StubSeedAdapter("eks-staging", "eks-staging seed dispatch is not implemented yet"),
    }


def default_selector_resolvers(command_runner: CommandRunner | None = None) -> dict[str, SelectorResolver]:
    return {
        "pod_label_selector": PodLabelSelectorResolver(command_runner),
        "deployment_label_selector": KubernetesNamedResourceSelectorResolver(
            kind="deployment_label_selector",
            target_input="deployment",
            resource="deployment",
            command_runner=command_runner,
        ),
        "service_label_selector": KubernetesNamedResourceSelectorResolver(
            kind="service_label_selector",
            target_input="service",
            resource="service",
            command_runner=command_runner,
        ),
        "node_label_selector": NodeLabelSelectorResolver(command_runner),
        "pvc_label_selector": KubernetesNamedResourceSelectorResolver(
            kind="pvc_label_selector",
            target_input="pvc",
            resource="pvc",
            command_runner=command_runner,
        ),
        "pod_label_selector_list": PodLabelSelectorListResolver(command_runner),
    }


def default_predicates(command_runner: CommandRunner | None = None) -> dict[str, Predicate]:
    implemented: dict[str, Predicate] = {
        "pod_phase": PodPhasePredicate(command_runner),
        "pod_event_reason": PodEventReasonPredicate(command_runner),
        "pod_condition": PodConditionPredicate(command_runner),
        "pod_restart_count_min": PodRestartCountMinPredicate(command_runner),
        "deployment_replicas_ready": DeploymentReplicasReadyPredicate(command_runner),
        "node_condition": NodeConditionPredicate(command_runner),
        "pvc_phase": PvcPhasePredicate(command_runner),
        "prometheus_query_threshold": PrometheusQueryThresholdPredicate(command_runner),
        "postgres_connection_count_min": PostgresConnectionCountMinPredicate(command_runner),
        "loki_log_match": LokiLogMatchPredicate(command_runner),
        "http_endpoint_status": HttpEndpointStatusPredicate(command_runner),
        "linux_disk_usage_min": LinuxDiskUsageMinPredicate(command_runner),
        "linux_inode_usage_min": LinuxInodeUsageMinPredicate(command_runner),
        "linux_deleted_open_files_min": LinuxDeletedOpenFilesMinPredicate(command_runner),
        "linux_load_avg_min": LinuxLoadAvgMinPredicate(command_runner),
        "linux_cpu_usage_min": LinuxCpuUsageMinPredicate(command_runner),
        "linux_memory_usage_min": LinuxMemoryUsageMinPredicate(command_runner),
        "linux_oom_events_min": LinuxOomEventsMinPredicate(command_runner),
        "chaos_mesh_phase": ChaosMeshPhasePredicate(command_runner),
        "tls_certificate_invalid": TlsCertificateInvalidPredicate(command_runner),
        "dns_resolution_fails": DnsResolutionFailsPredicate(command_runner),
        "kafka_consumer_lag_min": KafkaConsumerLagMinPredicate(command_runner),
        "kafka_partition_rebalance_active": KafkaPartitionRebalanceActivePredicate(command_runner),
        "queue_dead_letter_min": QueueDeadLetterMinPredicate(command_runner),
    }
    return implemented


def _messaging_state_args(params: Mapping[str, Any], inputs: Mapping[str, Any], key: str) -> list[str]:
    namespace = str(params.get("namespace") or inputs.get("namespace") or "default")
    configmap = str(params.get("messaging_evidence_configmap") or inputs.get("messaging_evidence_configmap") or "sre-agent-messaging-evidence")
    return [str(MESSAGING_STATE_READ_SCRIPT), namespace, configmap, key]


def _numeric_check(value: Any, comparator: str, threshold: Any) -> bool | None:
    if threshold is None:
        return None
    try:
        return _compare(float(value), comparator, float(threshold))
    except (TypeError, ValueError):
        return False


def _container_repo_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError(f"{resolved} must live under repo root {REPO_ROOT} to be copied into linux-target") from exc
    return f"/sre-agent/{relative.as_posix()}"


def _container_dir_path(path: str) -> str:
    return str(Path(path).parent).replace("\\", "/")


def _linux_vm_exec_args(ctx: Any, command: list[str]) -> list[str]:
    args = ["docker", "compose", "-f", str(LINUX_VM_COMPOSE_FILE), "exec", "-T"]
    args.extend(_linux_vm_profile_env_flags(ctx))
    args.append(LINUX_VM_TARGET_SERVICE)
    args.extend(command)
    return args


def _linux_vm_cp_args(source: Path, container_path: str) -> list[str]:
    return [
        "docker",
        "compose",
        "-f",
        str(LINUX_VM_COMPOSE_FILE),
        "cp",
        str(source.resolve()),
        f"{LINUX_VM_TARGET_SERVICE}:{container_path}",
    ]


def _linux_vm_refresh_repo_files(
    ctx: Any,
    command_runner: CommandRunner,
    paths: tuple[Path, ...],
    *,
    cwd: Path,
) -> dict[str, str] | None:
    dirs = sorted({_container_dir_path(_container_repo_path(path)) for path in paths})
    for directory in dirs:
        completed = command_runner(_linux_vm_exec_args(ctx, ["mkdir", "-p", directory]), env=ctx.host_env, cwd=cwd)
        if completed.returncode != 0:
            return {"check": "linux_vm_prepare", "error": _command_error(completed, "failed to prepare linux-vm seed path")}
    for path in paths:
        container_path = _container_repo_path(path)
        completed = command_runner(_linux_vm_cp_args(path, container_path), env=ctx.host_env, cwd=cwd)
        if completed.returncode != 0:
            return {"check": "linux_vm_seed_copy", "error": _command_error(completed, "failed to copy linux-vm seed file")}
    return None


def _linux_vm_profile_env_flags(ctx: Any) -> list[str]:
    profile = getattr(ctx, "provider_profile", None)
    host_env = getattr(ctx, "host_env", {}) or {}
    if not isinstance(profile, ProviderProfile):
        return []
    flags: list[str] = []
    for key in sorted(profile.environment):
        if key in host_env:
            flags.extend(["--env", f"{key}={host_env[key]}"])
    return flags


def _chaos_phase_matches(observed: str, expected: str) -> bool:
    if observed == expected:
        return True
    return _normalize_chaos_phase(observed) == _normalize_chaos_phase(expected)


def _normalize_chaos_phase(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "", str(value or "").strip().lower())
    aliases = {
        "run": "running",
        "running": "running",
        "injected": "running",
        "injecting": "running",
        "pause": "paused",
        "paused": "paused",
        "stop": "stopped",
        "stopped": "stopped",
    }
    return aliases.get(normalized, normalized)


def _tls_failure_observation(
    completed: subprocess.CompletedProcess,
    *,
    namespace: str,
    service: str,
    hostname: str,
    probe: str,
    ctx: Any,
    command_runner: CommandRunner,
) -> dict[str, Any]:
    observed: dict[str, Any] = {
        "error": _command_error(completed, "tls check failed"),
        "returncode": completed.returncode,
        "namespace": namespace,
        "service": service,
        "hostname": hostname,
        "probe": probe,
        "kubernetes": _tls_kubernetes_state(namespace, service, probe, ctx, command_runner),
    }
    stdout = _bounded_text(completed.stdout)
    stderr = _bounded_text(completed.stderr)
    if stdout:
        observed["stdout"] = stdout
    if stderr:
        observed["stderr"] = stderr
    return observed


def _tls_kubernetes_state(
    namespace: str,
    service: str,
    probe: str,
    ctx: Any,
    command_runner: CommandRunner,
) -> dict[str, Any]:
    return {
        "service": _kubectl_jsonpath(
            ["kubectl", "-n", namespace, "get", "service", service, "-o", "jsonpath={.spec.clusterIP}"],
            ctx,
            command_runner,
        ),
        "endpoints": _kubectl_jsonpath(
            ["kubectl", "-n", namespace, "get", "endpoints", service, "-o", "jsonpath={.subsets[*].addresses[*].ip}"],
            ctx,
            command_runner,
        ),
        "probe": _kubectl_jsonpath(
            ["kubectl", "-n", namespace, "get", "pod", probe, "-o", "jsonpath={.status.phase}"],
            ctx,
            command_runner,
        ),
    }


def _kubectl_jsonpath(args: list[str], ctx: Any, command_runner: CommandRunner) -> dict[str, Any]:
    completed = command_runner(args, env=ctx.host_env)
    if completed.returncode == 0:
        return {"ok": True, "value": _bounded_text(completed.stdout)}
    return {
        "ok": False,
        "error": _bounded_text(_command_error(completed, "kubectl lookup failed")),
        "returncode": completed.returncode,
    }


def _bounded_text(value: str | None, *, limit: int = 500) -> str:
    text = (value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "...[truncated]"


def _run_subprocess(args: list[str], *, env: Mapping[str, str] | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        cwd=cwd,
        env=dict(env) if env is not None else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def _command_error(completed: subprocess.CompletedProcess, fallback: str) -> str:
    return (completed.stderr or completed.stdout or "").strip() or fallback


def _is_executable(path: Path) -> bool:
    return path.is_file() and os.access(path, os.X_OK)


def _absolute(path: Path) -> str:
    """Return the absolute path string. Seed adapters set cwd= for the
    subprocess, so any relative path arg would otherwise be resolved
    against the new cwd and double up. Always pass absolute to the
    underlying tools."""
    return str(path.resolve())


def _split_names(value: str) -> list[str]:
    return [item for item in value.split() if item]


def _parse_ints(value: str) -> list[int]:
    return [int(item) for item in value.split() if re.fullmatch(r"-?\d+", item)]


def _first_float(value: str) -> float | None:
    parts = value.split()
    if not parts:
        return None
    try:
        return float(parts[0])
    except ValueError:
        return None


def _df_usage_percent(value: str) -> float | None:
    lines = [line.split() for line in value.splitlines() if line.strip()]
    if len(lines) < 2 or len(lines[1]) < 5:
        return None
    raw = lines[1][4].rstrip("%")
    try:
        return float(raw)
    except ValueError:
        return None


def _deleted_open_file_count(value: str) -> int:
    return sum(1 for line in value.splitlines() if "(deleted)" in line.lower())


def _mpstat_used_percent(value: str) -> float | None:
    for line in reversed([line.strip() for line in value.splitlines() if line.strip()]):
        parts = line.split()
        if len(parts) >= 3 and parts[0].startswith("Average:") and parts[1] == "all":
            try:
                return round(100.0 - float(parts[-1]), 1)
            except ValueError:
                return None
    return None


def _free_used_percent(value: str) -> float | None:
    for line in value.splitlines():
        parts = line.split()
        if len(parts) >= 7 and parts[0] == "Mem:":
            try:
                total = float(parts[1])
                used = float(parts[2])
            except ValueError:
                return None
            return round((used / total) * 100.0, 1) if total else None
    return None


def _oom_event_count(value: str) -> int:
    return sum(1 for line in value.splitlines() if re.search(r"out of memory|oom-kill|killed process", line, re.IGNORECASE))


def _compare(value: float, comparator: str, threshold: float) -> bool:
    if comparator == "gt":
        return value > threshold
    if comparator == "gte":
        return value >= threshold
    if comparator == "lt":
        return value < threshold
    if comparator == "lte":
        return value <= threshold
    if comparator == "eq":
        return value == threshold
    return False


def _prometheus_values(payload: str) -> list[float]:
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return []
    result = parsed.get("data", {}).get("result", [])
    values: list[float] = []
    for item in result if isinstance(result, list) else []:
        raw = item.get("value", [None, None]) if isinstance(item, dict) else [None, None]
        if len(raw) < 2:
            continue
        try:
            values.append(float(raw[1]))
        except (TypeError, ValueError):
            continue
    return values


def _loki_line_count(payload: str) -> int:
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError:
        return 0
    result = parsed.get("data", {}).get("result", [])
    count = 0
    for stream in result if isinstance(result, list) else []:
        values = stream.get("values", []) if isinstance(stream, dict) else []
        count += len(values) if isinstance(values, list) else 0
    return count


def _select_by_cardinality(key: str, cardinality: str, matches: list[str]) -> tuple[Any, dict[str, Any] | None]:
    if cardinality == "list":
        return list(matches), None
    if cardinality == "first":
        if not matches:
            return None, {"check": key, "error": "expected at least one selector match", "matched": []}
        return sorted(matches)[0], None
    if cardinality == "exactly_one" and len(matches) != 1:
        return None, {
            "check": key,
            "error": f"expected exactly one selector match, observed {len(matches)}",
            "matched": list(matches),
        }
    return matches[0], None


def _render_templates(value: Any, inputs: Mapping[str, Any]) -> Any:
    if isinstance(value, dict):
        return {key: _render_templates(item, inputs) for key, item in value.items()}
    if isinstance(value, list):
        return [_render_templates(item, inputs) for item in value]
    if isinstance(value, str):
        rendered = value
        for key, item in inputs.items():
            rendered = rendered.replace("{{" + str(key) + "}}", str(item))
        return rendered
    return value


def _wait_timeout_failures(results: list[tuple[dict[str, Any], PredicateResult]]) -> list[dict[str, Any]]:
    failures = []
    for spec, result in results:
        if result.matched:
            continue
        failures.append(
            {
                "check": str(spec.get("kind") or "wait_for"),
                "error": "wait_for predicate did not match before timeout",
                "observed": result.observed,
            }
        )
    return failures or [{"check": "wait_for", "error": "wait_for timed out before any predicates matched"}]


def _forward_specs_for_profile(profile: ProviderProfile) -> list[tuple[str, str, int]]:
    specs: list[tuple[str, str, int]] = []
    seen: set[tuple[str, str, int]] = set()
    for value in profile.endpoints.values():
        parsed = urlparse(value)
        host = parsed.hostname or ""
        if not parsed.scheme or not host or host in {"localhost", "127.0.0.1"}:
            continue
        service, namespace = _service_namespace_from_host(host)
        remote_port = int(parsed.port or (443 if parsed.scheme == "https" else 80))
        key = (service, namespace, remote_port)
        if key not in seen:
            specs.append(key)
            seen.add(key)
    return specs


def _service_namespace_from_host(host: str) -> tuple[str, str]:
    parts = host.split(".")
    service = parts[0]
    namespace = parts[1] if len(parts) > 1 and parts[1] else "observability"
    return service, namespace
