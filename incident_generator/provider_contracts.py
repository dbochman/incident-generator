"""Provider command contracts for future real evidence backends."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import urlparse, urlunparse


MAX_INPUT_LENGTH = 2048
ENV_SUBSTITUTION_RE = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")

DEFAULT_INPUT_ALLOWLISTS = {
    "consumer_group": r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}",
    "database": r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}",
    "host": r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,253}",
    "hostname": r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,253}",
    "mount": r"/[A-Za-z0-9._/@:+,=-]*",
    "namespace": r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}",
    "node": r"[A-Za-z0-9][A-Za-z0-9_.-]{0,253}",
    "path": r"/[A-Za-z0-9._/@:+,=-]*",
    "pod": r"[A-Za-z0-9][A-Za-z0-9_.-]{0,253}",
    "queue": r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}",
    "service": r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}",
    "target": r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,253}",
    "time_window": r"[0-9]{1,4}[smhdw]",
    "url": r"https?://[A-Za-z0-9][A-Za-z0-9._~:/?#@%+=,&-]{0,2040}",
}


@dataclass(frozen=True)
class ProviderEvidenceContract:
    provider: str
    adapter_id: str
    command_template: str
    required_inputs: tuple[str, ...]
    fixture_key: str
    output_format: str
    parser_contract: str
    timeout_seconds: int
    redaction_required: bool = True
    input_allowlists: dict[str, str] | None = None

    def render_command(self, inputs: dict[str, Any]) -> str:
        missing = [key for key in self.required_inputs if key not in inputs or inputs[key] in (None, "")]
        if missing:
            raise ValueError(f"Missing inputs for {self.adapter_id}: {', '.join(missing)}")

        safe_inputs = self._validated_inputs(inputs)
        rendered = self.command_template
        for key in self.required_inputs:
            rendered = rendered.replace("{{" + key + "}}", safe_inputs[key])

        unresolved = sorted(set(re.findall(r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}", rendered)))
        if unresolved:
            raise ValueError(f"Unresolved command template inputs for {self.adapter_id}: {', '.join(unresolved)}")
        return rendered

    def _validated_inputs(self, inputs: dict[str, Any]) -> dict[str, str]:
        safe_inputs = {}
        for key in self.required_inputs:
            value = str(inputs[key])
            pattern = (self.input_allowlists or {}).get(key, DEFAULT_INPUT_ALLOWLISTS.get(key))
            if pattern is None:
                raise ValueError(f"No input allowlist registered for {self.adapter_id}: {key}")
            if len(value) > MAX_INPUT_LENGTH or not re.fullmatch(pattern, value):
                raise ValueError(f"Unsafe input for {self.adapter_id}: {key} does not match allowlist")
            if key in {"mount", "path"} and ".." in value.split("/"):
                raise ValueError(f"Unsafe input for {self.adapter_id}: {key} may not contain parent traversal")
            safe_inputs[key] = value
        return safe_inputs


@dataclass(frozen=True)
class ProviderProfile:
    name: str
    environment: dict[str, str]
    endpoints: dict[str, str]


def resolve_environment(profile: ProviderProfile, host_env: Mapping[str, str]) -> dict[str, str]:
    """Resolve ${VAR} substitutions in profile.environment from host_env."""
    missing: set[str] = set()
    resolved: dict[str, str] = {}
    for key, value in profile.environment.items():
        names = ENV_SUBSTITUTION_RE.findall(value)
        for name in names:
            if name not in host_env:
                missing.add(name)
        if not any(name not in host_env for name in names):
            resolved[key] = ENV_SUBSTITUTION_RE.sub(lambda match: host_env[match.group(1)], value)
    if missing:
        names = ", ".join(sorted(missing))
        raise ValueError(f"missing host environment variables for profile {profile.name}: {names}")
    return resolved


def rewrite_endpoints_for_local_ports(profile: ProviderProfile, forwards: list[Any]) -> ProviderProfile:
    """Return a profile whose cluster-internal URLs target forwarded localhost ports."""
    if not forwards:
        return profile

    environment = dict(profile.environment)
    endpoints = dict(profile.endpoints)
    matched_forwards: set[str] = set()
    for forward in forwards:
        service = str(forward.service)
        local_port = int(forward.local_port)
        forward_key = _forward_key(forward)
        environment = {
            key: _rewrite_url_for_forward(value, service, local_port, matched_forwards, forward_key)
            for key, value in environment.items()
        }
        endpoints = {
            key: _rewrite_url_for_forward(value, service, local_port, matched_forwards, forward_key)
            for key, value in endpoints.items()
        }

    unmatched = [_forward_key(forward) for forward in forwards if _forward_key(forward) not in matched_forwards]
    if unmatched:
        raise ValueError(f"unmatched forwarded ports for profile {profile.name}: {', '.join(sorted(unmatched))}")
    return ProviderProfile(name=profile.name, environment=environment, endpoints=endpoints)


def _rewrite_url_for_forward(
    value: str,
    service: str,
    local_port: int,
    matched_forwards: set[str],
    forward_key: str,
) -> str:
    parsed = urlparse(value)
    host = parsed.hostname or ""
    if not parsed.scheme or not host:
        return value
    if not _host_matches_service(host, service):
        return value
    matched_forwards.add(forward_key)
    return urlunparse(parsed._replace(netloc=f"localhost:{local_port}"))


def _host_matches_service(host: str, service: str) -> bool:
    normalized_host = host.lower()
    normalized_service = service.lower()
    return normalized_host == normalized_service or normalized_host.startswith(f"{normalized_service}.")


def _forward_key(forward: Any) -> str:
    return f"{forward.namespace}/{forward.service}:{forward.remote_port}"


def default_provider_profiles() -> list[ProviderProfile]:
    return [
        ProviderProfile(
            name="harness-local",
            environment={
                "KUBECONFIG": "${SRE_AGENT_KIND_KUBECONFIG}",
                "PAGERDUTY_API_URL": "http://fake-pagerduty.observability.svc:8080",
                "PROMETHEUS_URL": "http://kube-prometheus-stack-prometheus.observability.svc:9090",
                "LOKI_URL": "http://loki.observability.svc:3100",
                "TEMPO_URL": "http://tempo.observability.svc:3100",
            },
            endpoints={
                "pagerduty": "http://fake-pagerduty.observability.svc:8080",
                "prometheus": "http://kube-prometheus-stack-prometheus.observability.svc:9090",
                "loki": "http://loki.observability.svc:3100",
                "tempo": "http://tempo.observability.svc:3100",
            },
        ),
        ProviderProfile(
            name="harness-local-linux-vm",
            environment={
                "PAGERDUTY_API_URL": "http://localhost:8081",
                "PROMETHEUS_URL": "http://localhost:9090",
                "LOKI_URL": "http://localhost:3100",
                "TEMPO_URL": "http://localhost:3200",
            },
            endpoints={
                "pagerduty": "http://localhost:8081",
                "prometheus": "http://localhost:9090",
                "loki": "http://localhost:3100",
                "tempo": "http://localhost:3200",
            },
        ),
    ]


def provider_profile(name: str) -> ProviderProfile:
    for profile in default_provider_profiles():
        if profile.name == name:
            return profile
    raise KeyError(f"unknown provider profile: {name}")


def default_provider_contracts() -> list[ProviderEvidenceContract]:
    return [
        ProviderEvidenceContract(
            provider="kubernetes",
            adapter_id="kubernetes.pod_summary",
            command_template="kubectl get pod {{pod}} -n {{namespace}} -o wide",
            required_inputs=("namespace", "pod"),
            fixture_key="pod_summary",
            output_format="kubectl_table",
            parser_contract="pod readiness, status, restart count, age, IP, and node",
            timeout_seconds=10,
        ),
        ProviderEvidenceContract(
            provider="kubernetes",
            adapter_id="kubernetes.pod_describe",
            command_template="kubectl describe pod {{pod}} -n {{namespace}}",
            required_inputs=("namespace", "pod"),
            fixture_key="pod_describe",
            output_format="kubectl_describe",
            parser_contract="container state, last termination, exit code, reason, and events",
            timeout_seconds=15,
        ),
        ProviderEvidenceContract(
            provider="kubernetes",
            adapter_id="kubernetes.pod_logs.previous",
            command_template="kubectl logs {{pod}} -n {{namespace}} --previous",
            required_inputs=("namespace", "pod"),
            fixture_key="previous_logs",
            output_format="redacted_log_lines",
            parser_contract="previous container log lines summarized into crash/error signals",
            timeout_seconds=15,
        ),
        ProviderEvidenceContract(
            provider="kubernetes",
            adapter_id="kubernetes.pod_logs.current",
            command_template="kubectl logs {{pod}} -n {{namespace}}",
            required_inputs=("namespace", "pod"),
            fixture_key="current_logs",
            output_format="redacted_log_lines",
            parser_contract="current container log lines summarized into startup/error signals",
            timeout_seconds=15,
        ),
        ProviderEvidenceContract(
            provider="kubernetes",
            adapter_id="kubernetes.node_conditions",
            command_template="kubectl describe node {{node}}",
            required_inputs=("node",),
            fixture_key="node_conditions",
            output_format="kubectl_describe",
            parser_contract="node Ready, MemoryPressure, DiskPressure, PIDPressure, and event details",
            timeout_seconds=15,
        ),
        ProviderEvidenceContract(
            provider="linux",
            adapter_id="linux.disk_usage",
            command_template="ssh {{host}} df -P {{mount}}",
            required_inputs=("host", "mount"),
            fixture_key="filesystem_summary",
            output_format="df",
            parser_contract="filesystem size, used, available, and use percentage",
            timeout_seconds=10,
        ),
        ProviderEvidenceContract(
            provider="linux",
            adapter_id="linux.inode_usage",
            command_template="ssh {{host}} df -Pi {{mount}}",
            required_inputs=("host", "mount"),
            fixture_key="inode_summary",
            output_format="df",
            parser_contract="filesystem inode size, used, available, and use percentage",
            timeout_seconds=10,
        ),
        ProviderEvidenceContract(
            provider="linux",
            adapter_id="linux.directory_sizes",
            command_template="ssh {{host}} du -xhd1 {{path}}",
            required_inputs=("host", "path"),
            fixture_key="largest_paths",
            output_format="du",
            parser_contract="directory size rows sorted by apparent disk usage",
            timeout_seconds=30,
        ),
        ProviderEvidenceContract(
            provider="linux",
            adapter_id="linux.deleted_open_files",
            command_template="ssh {{host}} lsof +L1 {{mount}}",
            required_inputs=("host", "mount"),
            fixture_key="deleted_open_files",
            output_format="lsof",
            parser_contract="deleted open file count, bytes, process, and path details",
            timeout_seconds=20,
        ),
        ProviderEvidenceContract(
            provider="linux",
            adapter_id="linux.load_average",
            command_template="ssh {{host}} uptime",
            required_inputs=("host",),
            fixture_key="load_average",
            output_format="uptime",
            parser_contract="1m, 5m, and 15m load averages",
            timeout_seconds=10,
        ),
        ProviderEvidenceContract(
            provider="linux",
            adapter_id="linux.cpu_summary",
            command_template="ssh {{host}} mpstat 1 1",
            required_inputs=("host",),
            fixture_key="cpu_summary",
            output_format="mpstat",
            parser_contract="aggregate CPU idle and used percentages",
            timeout_seconds=15,
        ),
        ProviderEvidenceContract(
            provider="linux",
            adapter_id="linux.top_processes",
            command_template="ssh {{host}} ps -eo pid,user,pcpu,pmem,comm --sort=-pcpu",
            required_inputs=("host",),
            fixture_key="top_processes",
            output_format="ps",
            parser_contract="top CPU-consuming process rows",
            timeout_seconds=10,
        ),
        ProviderEvidenceContract(
            provider="linux",
            adapter_id="linux.memory_summary",
            command_template="ssh {{host}} free -m",
            required_inputs=("host",),
            fixture_key="memory_summary",
            output_format="free",
            parser_contract="memory and swap total, used, free, and available values",
            timeout_seconds=10,
        ),
        ProviderEvidenceContract(
            provider="linux",
            adapter_id="linux.top_memory_processes",
            command_template="ssh {{host}} ps -eo pid,user,pcpu,pmem,rss,comm --sort=-pmem",
            required_inputs=("host",),
            fixture_key="top_memory_processes",
            output_format="ps",
            parser_contract="top resident-memory-consuming process rows",
            timeout_seconds=10,
        ),
        ProviderEvidenceContract(
            provider="linux",
            adapter_id="linux.oom_events",
            command_template="ssh {{host}} journalctl -k --since {{time_window}} --grep OOM",
            required_inputs=("host", "time_window"),
            fixture_key="oom_events",
            output_format="journalctl",
            parser_contract="kernel OOM kill event count and representative log entries",
            timeout_seconds=20,
        ),
        ProviderEvidenceContract(
            provider="http",
            adapter_id="service.endpoint_check",
            command_template="curl -fsS -o /dev/null -w 'status=%{http_code} time_total=%{time_total}' {{url}}",
            required_inputs=("url",),
            fixture_key="endpoint_check",
            output_format="curl_write_out",
            parser_contract="HTTP status and total request time in curl write-out format",
            timeout_seconds=10,
        ),
        ProviderEvidenceContract(
            provider="prometheus",
            adapter_id="service.saturation_metrics",
            command_template="promql service-saturation --service {{service}} --since {{time_window}}",
            required_inputs=("service", "time_window"),
            fixture_key="saturation_metrics",
            output_format="key_value_lines",
            parser_contract="summary line plus optional pod=, dependency=, route=, and event= rows",
            timeout_seconds=15,
        ),
        ProviderEvidenceContract(
            provider="loki",
            adapter_id="service.error_logs",
            command_template="logcli query --since={{time_window}} '{service=\"{{service}}\"} |= \"ERROR\"'",
            required_inputs=("service", "time_window"),
            fixture_key="error_logs",
            output_format="redacted_log_lines",
            parser_contract="recent service log lines summarized into signal names and representative entries",
            timeout_seconds=20,
        ),
        ProviderEvidenceContract(
            provider="loki",
            adapter_id="service.structured_log_signatures",
            command_template="logcli summary --service {{service}} --since {{time_window}} --group-by signature,route,version,status",
            required_inputs=("service", "time_window"),
            fixture_key="structured_log_signatures",
            output_format="key_value_lines",
            parser_contract="signature= rows plus optional route=, version=, and sample rows",
            timeout_seconds=20,
        ),
        ProviderEvidenceContract(
            provider="prometheus",
            adapter_id="service.slo_status",
            command_template="promql service-slo --service {{service}} --since {{time_window}}",
            required_inputs=("service", "time_window"),
            fixture_key="slo_status",
            output_format="key_value_lines",
            parser_contract="service SLO summary plus optional route= and event= rows",
            timeout_seconds=15,
        ),
        ProviderEvidenceContract(
            provider="pagerduty",
            adapter_id="pagerduty.escalation_state",
            command_template="pdctl incidents --service {{service}} --since {{time_window}} --include escalation_policy,on_call",
            required_inputs=("service", "time_window"),
            fixture_key="pagerduty_escalation",
            output_format="key_value_lines",
            parser_contract="incident summary plus optional on_call, escalation, and event rows",
            timeout_seconds=20,
        ),
        ProviderEvidenceContract(
            provider="pagerduty",
            adapter_id="incident.timeline",
            command_template="pdctl timeline --service {{service}} --since {{time_window}} --include impact,pages",
            required_inputs=("service", "time_window"),
            fixture_key="incident_timeline",
            output_format="key_value_lines",
            parser_contract="incident impact summary plus event= rows",
            timeout_seconds=20,
        ),
        ProviderEvidenceContract(
            provider="deploy_metadata",
            adapter_id="service.recent_deploys",
            command_template="deployctl releases --service {{service}} --recent",
            required_inputs=("service",),
            fixture_key="recent_deploys",
            output_format="key_value_lines",
            parser_contract="recent deployment rows with deploy time, version, actor, and status",
            timeout_seconds=15,
        ),
        ProviderEvidenceContract(
            provider="deploy_metadata",
            adapter_id="service.deploy_metadata",
            command_template="deployctl metadata --service {{service}} --latest",
            required_inputs=("service",),
            fixture_key="deploy_metadata",
            output_format="key_value_lines",
            parser_contract="deployment summary plus optional change and annotation rows",
            timeout_seconds=15,
        ),
        ProviderEvidenceContract(
            provider="opentelemetry",
            adapter_id="service.trace_summary",
            command_template="otelctl trace-summary --service {{service}} --since {{time_window}}",
            required_inputs=("service", "time_window"),
            fixture_key="trace_summary",
            output_format="key_value_lines",
            parser_contract="span rows with duration, route, dependency, and status attributes",
            timeout_seconds=20,
        ),
        ProviderEvidenceContract(
            provider="opentelemetry",
            adapter_id="service.span_attributes",
            command_template="otelctl span-attributes --service {{service}} --since {{time_window}}",
            required_inputs=("service", "time_window"),
            fixture_key="span_attributes",
            output_format="key_value_lines",
            parser_contract="span attribute rows for route, peer service, deployment version, and error context",
            timeout_seconds=20,
        ),
        ProviderEvidenceContract(
            provider="dns",
            adapter_id="service.dns_lookup",
            command_template="dnsctl lookup --hostname {{hostname}}",
            required_inputs=("hostname",),
            fixture_key="dns_lookup",
            output_format="key_value_lines",
            parser_contract="DNS status, resolved records, and error reason when resolution fails",
            timeout_seconds=10,
        ),
        ProviderEvidenceContract(
            provider="tls",
            adapter_id="service.tls_check",
            command_template="tlsctl check --hostname {{hostname}}",
            required_inputs=("hostname",),
            fixture_key="tls_check",
            output_format="key_value_lines",
            parser_contract="certificate validity, hostname match, issuer, and expiry details",
            timeout_seconds=10,
        ),
        ProviderEvidenceContract(
            provider="queue",
            adapter_id="queue.consumer_lag",
            command_template="queuectl consumer-lag --queue {{queue}} --consumer-group {{consumer_group}}",
            required_inputs=("queue", "consumer_group"),
            fixture_key="queue_consumer_lag",
            output_format="key_value_lines",
            parser_contract="queue lag summary plus optional partition= rows",
            timeout_seconds=15,
        ),
        ProviderEvidenceContract(
            provider="queue",
            adapter_id="queue.dead_letter",
            command_template="queuectl dead-letter --queue {{queue}} --since {{time_window}}",
            required_inputs=("queue", "time_window"),
            fixture_key="queue_dead_letter",
            output_format="redacted_log_lines",
            parser_contract="dead-letter queue summary plus representative sample rows",
            timeout_seconds=20,
        ),
        ProviderEvidenceContract(
            provider="kafka",
            adapter_id="kafka.consumer_group_state",
            command_template="kafka-consumer-groups --describe --group {{consumer_group}} --topic {{queue}}",
            required_inputs=("queue", "consumer_group"),
            fixture_key="kafka_group_state",
            output_format="key_value_lines",
            parser_contract="consumer group state summary plus optional member= rows",
            timeout_seconds=20,
        ),
        ProviderEvidenceContract(
            provider="database",
            adapter_id="database.pool_status",
            command_template="dbctl pool-status --database {{database}}",
            required_inputs=("database",),
            fixture_key="db_pool",
            output_format="key_value_lines",
            parser_contract="pool utilization, saturation, churn, and optional event rows",
            timeout_seconds=15,
        ),
        ProviderEvidenceContract(
            provider="network",
            adapter_id="network.ping_summary",
            command_template="ping -c 5 {{target}}",
            required_inputs=("target",),
            fixture_key="ping_summary",
            output_format="ping_summary",
            parser_contract="packet-loss percentage and RTT summary",
            timeout_seconds=10,
        ),
        ProviderEvidenceContract(
            provider="network",
            adapter_id="network.mtr_summary",
            command_template="mtr --report --report-cycles 5 {{target}}",
            required_inputs=("target",),
            fixture_key="mtr_summary",
            output_format="mtr_report",
            parser_contract="hop-level loss and latency summary",
            timeout_seconds=20,
        ),
    ]


def provider_contracts_by_adapter() -> dict[str, ProviderEvidenceContract]:
    return {contract.adapter_id: contract for contract in default_provider_contracts()}


def contracts_for_provider(provider: str) -> list[ProviderEvidenceContract]:
    return [
        contract
        for contract in default_provider_contracts()
        if contract.provider == provider
    ]
