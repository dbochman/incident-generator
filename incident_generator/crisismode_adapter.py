"""Fixture-safe CrisisMode compatibility adapter for agent-adapter requests."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence, TextIO


REQUEST_SCHEMA_VERSION = "incident-generator.agent-adapter-request/v1"
RESPONSE_SCHEMA_VERSION = "incident-generator.agent-adapter-response/v1"
FINAL_RESPONSE_SCHEMA_VERSION = "incident-generator.agent-investigation-final-response/v2"
TOOL_REQUEST_SCHEMA_VERSION = "incident-generator.agent-investigation-tool-request/v2"
DEFAULT_CRISISMODE_COMPATIBILITY_BENCHMARK_SET_RELATIVE = Path("harness/crisismode-compatibility-benchmark-set.yaml")
ADAPTER_ID = "crisismode.incident-generator-adapter"
ADAPTER_VERSION = "0.2.0"
REQUIRED_OUTPUT_SECTIONS = [
    "hypotheses_ranked",
    "evidence_refs",
    "recommended_next_steps",
    "proposed_actions",
    "abstention",
    "uncertainty",
    "unsafe_actions_avoided",
]


@dataclass(frozen=True)
class SymptomSignal:
    """CrisisMode-style signal derived from redacted incident evidence."""

    type: str
    source: str
    detail: str
    severity: str
    evidence_id: str | None


CRISISMODE_ROUTE_RULES: list[dict[str, Any]] = [
    {
        "scenario": "database-connection-exhaustion",
        "agent_kind": "postgresql",
        "signal_types": ["connection", "timeout", "error_rate"],
        "keywords": ["connection", "pool", "exhaust", "max_connections", "database", "postgres", "pg"],
        "base_weight": 0.5,
        "reasoning": "Connection exhaustion signals with database dependencies detected",
    },
    {
        "scenario": "postgresql-replication-lag",
        "agent_kind": "postgresql",
        "signal_types": ["replication", "latency", "timeout"],
        "keywords": ["replication", "replica", "lag", "standby", "wal", "slot", "postgres", "pg"],
        "base_weight": 0.6,
        "reasoning": "Replication lag or slot pressure signals with PostgreSQL recovery context",
    },
    {
        "scenario": "redis-memory-pressure",
        "agent_kind": "redis",
        "signal_types": ["cache_memory", "resource_exhaustion", "connection"],
        "keywords": ["redis", "memory", "eviction", "oom", "maxmemory", "cache", "clients"],
        "base_weight": 0.6,
        "reasoning": "Redis memory pressure or client exhaustion signals",
    },
    {
        "scenario": "queue-backlog",
        "agent_kind": "queue-backlog",
        "signal_types": ["queue_depth", "latency", "timeout"],
        "keywords": ["queue", "backlog", "worker", "stuck", "job", "consumer_lag"],
        "base_weight": 0.5,
        "reasoning": "Growing queue depth or stuck workers with queue dependencies",
    },
    {
        "scenario": "kubernetes-pod-crash-loop",
        "agent_kind": "kubernetes",
        "signal_types": ["error_rate", "resource_exhaustion"],
        "keywords": ["kubernetes", "k8s", "pod", "crash", "restart", "oom", "container", "crashloopbackoff"],
        "base_weight": 0.5,
        "reasoning": "Pod crash or resource exhaustion signals in a Kubernetes environment",
    },
    {
        "scenario": "deploy-rollback",
        "agent_kind": "deploy-rollback",
        "signal_types": ["error_rate", "deploy_change"],
        "keywords": ["deploy", "release", "rollback", "regression", "version", "canary", "new version"],
        "base_weight": 0.4,
        "reasoning": "High error rate correlated with a recent deployment change",
    },
    {
        "scenario": "config-drift",
        "agent_kind": "config-drift",
        "signal_types": ["config_mismatch", "deploy_change", "error_rate"],
        "keywords": ["config", "configuration", "env", "environment", "mismatch", "drift", "secret"],
        "base_weight": 0.4,
        "reasoning": "Configuration mismatch signals, possibly after a deployment",
    },
    {
        "scenario": "kafka-consumer-lag",
        "agent_kind": "kafka",
        "signal_types": ["queue_depth", "latency", "timeout"],
        "keywords": ["kafka", "consumer", "lag", "partition", "offset", "broker", "topic"],
        "base_weight": 0.6,
        "reasoning": "Consumer lag or partition signals with Kafka in the stack",
    },
    {
        "scenario": "etcd-consensus-loss",
        "agent_kind": "etcd",
        "signal_types": ["consensus", "connection", "timeout"],
        "keywords": ["etcd", "consensus", "leader", "quorum", "raft", "election"],
        "base_weight": 0.6,
        "reasoning": "Consensus or leader election failures with etcd recovery context",
    },
    {
        "scenario": "ceph-storage-degraded",
        "agent_kind": "ceph",
        "signal_types": ["storage", "resource_exhaustion", "latency"],
        "keywords": ["ceph", "osd", "storage", "placement", "degraded", "unfound", "nearfull"],
        "base_weight": 0.5,
        "reasoning": "Ceph OSD, placement group, or pool degradation signals",
    },
    {
        "scenario": "flink-checkpoint-failure",
        "agent_kind": "flink",
        "signal_types": ["stream_processing", "timeout", "latency"],
        "keywords": ["flink", "checkpoint", "backpressure", "stream", "pipeline", "taskmanager", "savepoint"],
        "base_weight": 0.5,
        "reasoning": "Flink checkpoint failure or backpressure signals",
    },
    {
        "scenario": "ai-provider-failover",
        "agent_kind": "ai-provider",
        "signal_types": ["timeout", "error_rate", "connection"],
        "keywords": ["openai", "anthropic", "llm", "rate limit", "429", "ai provider"],
        "base_weight": 0.4,
        "reasoning": "Timeout or error signals from AI provider endpoints",
    },
    {
        "scenario": "db-migration-stuck",
        "agent_kind": "db-migration",
        "signal_types": ["migration", "connection", "timeout"],
        "keywords": ["migration", "ddl", "lock", "schema_migrations", "pg_locks", "rollback", "long running"],
        "base_weight": 0.6,
        "reasoning": "Database migration or DDL lock signals with managed database recovery context",
    },
    {
        "scenario": "dns-resolution-failure",
        "agent_kind": "dns",
        "signal_types": ["dns", "connection", "error_rate"],
        "keywords": ["dns", "nxdomain", "resolver", "lookup", "coredns", "hostname"],
        "base_weight": 0.6,
        "reasoning": "DNS lookup or resolver failure signals with service reachability impact",
    },
    {
        "scenario": "tls-certificate-failure",
        "agent_kind": "tls",
        "signal_types": ["tls", "certificate", "error_rate"],
        "keywords": ["tls", "certificate", "expired", "hostname mismatch", "x509", "ssl"],
        "base_weight": 0.6,
        "reasoning": "TLS certificate validity or hostname mismatch signals with edge impact",
    },
    {
        "scenario": "disk-capacity-exhaustion",
        "agent_kind": "disk",
        "signal_types": ["disk", "resource_exhaustion", "error_rate"],
        "keywords": ["disk", "filesystem", "inode", "no space", "capacity", "df", "deleted open"],
        "base_weight": 0.6,
        "reasoning": "Disk byte, inode, or deleted-open-file exhaustion signals",
    },
    {
        "scenario": "backup-verification-failure",
        "agent_kind": "backup",
        "signal_types": ["backup", "storage", "timeout"],
        "keywords": ["backup", "restore", "snapshot", "verification", "rpo", "recovery point"],
        "base_weight": 0.55,
        "reasoning": "Backup verification or restore-readiness signals with recovery confidence impact",
    },
    {
        "scenario": "aws-s3-degradation",
        "agent_kind": "aws-s3",
        "signal_types": ["object_storage", "storage", "error_rate"],
        "keywords": ["s3", "bucket", "object", "putobject", "getobject", "slowdown", "503"],
        "base_weight": 0.6,
        "reasoning": "S3 object storage errors or throttling signals",
    },
    {
        "scenario": "aws-dynamodb-throttling",
        "agent_kind": "aws-dynamodb",
        "signal_types": ["dynamodb", "throttle", "error_rate"],
        "keywords": ["dynamodb", "throttle", "provisionedthroughput", "table", "wcu", "rcu"],
        "base_weight": 0.6,
        "reasoning": "DynamoDB throttling or capacity signals",
    },
    {
        "scenario": "aws-rds-failover",
        "agent_kind": "aws-rds",
        "signal_types": ["rds", "connection", "timeout"],
        "keywords": ["rds", "aurora", "failover", "replica", "database", "storage"],
        "base_weight": 0.6,
        "reasoning": "AWS RDS or Aurora failover and availability signals",
    },
]


GENERIC_SCENARIO_PROFILES: dict[str, dict[str, Any]] = {
    "postgresql-replication-lag": {
        "agent_kind": "postgresql",
        "summary": "postgresql replication lag is causing read path staleness",
        "confidence": "high",
        "inspect_action": "inspect_pg_replication",
        "draft_action": "draft_pg_replication_recovery_plan",
        "draft_summary": "Draft a PostgreSQL replication recovery plan for human review without executing it",
        "crisismode_plan": "postgresql-replication-recovery",
        "target": "postgresql-replica",
        "supports_claims": [
            "replication lag exceeds the accepted recovery point objective",
            "replica or slot evidence aligns with the degraded read path",
        ],
        "next_step": "Review replica lag, replication slots, and detach/reseed gates before approving recovery",
        "evidence_needed": ["pg_stat_replication", "pg_replication_slots", "traffic detachment gate"],
        "unsafe_actions": ["detach or reseed replica without database-owner approval", "drop replication slot without preserving WAL evidence"],
        "competing": ["database connection pool exhaustion", "application deploy regression"],
        "ref_needles": ["replication", "slot", "replica"],
    },
    "redis-memory-pressure": {
        "agent_kind": "redis",
        "summary": "redis memory pressure is causing cache availability degradation",
        "confidence": "high",
        "inspect_action": "inspect_redis_memory",
        "draft_action": "draft_redis_memory_recovery_plan",
        "draft_summary": "Draft a Redis memory recovery plan for human review without executing it",
        "crisismode_plan": "redis-memory-recovery",
        "target": "redis-cache",
        "supports_claims": [
            "Redis memory usage or evictions crossed the critical threshold",
            "client or cache error evidence aligns with Redis pressure",
        ],
        "next_step": "Review memory, client, and eviction evidence before approving cache recovery",
        "evidence_needed": ["redis INFO memory", "client pressure", "eviction rate"],
        "unsafe_actions": ["flush cache or change maxmemory policy without human approval", "disconnect clients without scoped evidence"],
        "competing": ["application deploy regression", "database connection pressure"],
        "ref_needles": ["redis", "memory", "eviction"],
    },
    "kafka-consumer-lag": {
        "agent_kind": "kafka",
        "summary": "kafka consumer lag is causing message processing delay",
        "confidence": "high",
        "inspect_action": "inspect_kafka_lag",
        "draft_action": "draft_kafka_recovery_plan",
        "draft_summary": "Draft a Kafka consumer lag recovery plan for human review without executing it",
        "crisismode_plan": "kafka-consumer-lag-recovery",
        "target": "checkout-consumer-group",
        "supports_claims": [
            "consumer lag increased sharply during the incident window",
            "Kafka partition or consumer group evidence aligns with processing delay",
        ],
        "next_step": "Review consumer group, partition, and broker state before approving recovery",
        "evidence_needed": ["consumer group lag", "partition health", "broker state"],
        "unsafe_actions": ["reset consumer offsets without human approval", "reassign partitions without preserving lag evidence"],
        "competing": ["queue worker saturation", "downstream dependency latency"],
        "ref_needles": ["kafka", "consumer", "partition", "lag"],
    },
    "etcd-consensus-loss": {
        "agent_kind": "etcd",
        "summary": "etcd leader election instability is degrading cluster control plane health",
        "confidence": "high",
        "inspect_action": "inspect_etcd_cluster",
        "draft_action": "draft_etcd_recovery_plan",
        "draft_summary": "Draft an etcd recovery plan for human review without executing it",
        "crisismode_plan": "etcd-consensus-recovery",
        "target": "etcd-cluster",
        "supports_claims": [
            "etcd leader election or quorum evidence is degraded",
            "member health evidence aligns with control plane instability",
        ],
        "next_step": "Review endpoint status, member list, and alarm state before approving consensus recovery",
        "evidence_needed": ["etcd endpoint status", "member list", "alarm list"],
        "unsafe_actions": ["remove etcd member without platform-lead approval", "restore snapshot without preserving cluster evidence"],
        "competing": ["kubernetes node instability", "network partition"],
        "ref_needles": ["etcd", "leader", "quorum", "member"],
    },
    "ceph-storage-degraded": {
        "agent_kind": "ceph",
        "summary": "ceph storage degradation is causing elevated storage latency",
        "confidence": "high",
        "inspect_action": "inspect_ceph_health",
        "draft_action": "draft_ceph_recovery_plan",
        "draft_summary": "Draft a Ceph storage recovery plan for human review without executing it",
        "crisismode_plan": "ceph-storage-recovery",
        "target": "ceph-cluster",
        "supports_claims": [
            "Ceph health reports degraded placement groups or OSD failures",
            "storage latency evidence aligns with Ceph degradation",
        ],
        "next_step": "Review OSD tree, placement group state, and pool health before approving recovery",
        "evidence_needed": ["ceph health detail", "OSD tree", "PG status"],
        "unsafe_actions": ["remove or reweight OSDs without storage-lead approval", "repair PGs before preserving health detail"],
        "competing": ["application latency", "network path degradation"],
        "ref_needles": ["ceph", "osd", "pg", "storage"],
    },
    "flink-checkpoint-failure": {
        "agent_kind": "flink",
        "summary": "flink checkpoint failures are causing stream processing backpressure",
        "confidence": "high",
        "inspect_action": "inspect_flink_job",
        "draft_action": "draft_flink_recovery_plan",
        "draft_summary": "Draft a Flink job recovery plan for human review without executing it",
        "crisismode_plan": "flink-checkpoint-recovery",
        "target": "checkout-stream-job",
        "supports_claims": [
            "checkpoint failures align with the incident window",
            "backpressure or TaskManager evidence confirms stream degradation",
        ],
        "next_step": "Review checkpoint history, job status, and backpressure before approving stream recovery",
        "evidence_needed": ["checkpoint history", "job status", "backpressure"],
        "unsafe_actions": ["restart Flink job without savepoint review", "change checkpoint config without approval"],
        "competing": ["Kafka consumer lag", "downstream sink latency"],
        "ref_needles": ["flink", "checkpoint", "backpressure", "taskmanager"],
    },
    "ai-provider-failover": {
        "agent_kind": "ai-provider",
        "summary": "ai provider degradation is causing request failures",
        "confidence": "high",
        "inspect_action": "inspect_ai_provider_status",
        "draft_action": "draft_ai_provider_failover_plan",
        "draft_summary": "Draft an AI provider failover plan for human review without executing it",
        "crisismode_plan": "ai-provider-failover",
        "target": "llm-provider-routing",
        "supports_claims": [
            "AI provider latency or rate-limit evidence is degraded",
            "application error evidence aligns with provider request failures",
        ],
        "next_step": "Review provider status, request metrics, and fallback chain before approving failover",
        "evidence_needed": ["provider health", "request metrics", "fallback chain status"],
        "unsafe_actions": ["trip circuit breaker without approval", "shift provider traffic without preserving provider evidence"],
        "competing": ["application regression", "network path degradation"],
        "ref_needles": ["openai", "anthropic", "llm", "provider", "429"],
    },
    "db-migration-stuck": {
        "agent_kind": "db-migration",
        "summary": "stuck database migration is blocking checkout database operations",
        "confidence": "high",
        "inspect_action": "inspect_db_migration",
        "draft_action": "draft_db_migration_recovery_plan",
        "draft_summary": "Draft a database migration recovery plan for human review without executing it",
        "crisismode_plan": "db-migration-recovery",
        "target": "checkout-database",
        "supports_claims": [
            "migration lock evidence shows a blocked DDL or migration runner",
            "database operation failures align with migration lock timing",
        ],
        "next_step": "Review locks, schema migration state, and rollback gates before approving database recovery",
        "evidence_needed": ["pg_locks", "schema_migrations", "migration rollback plan"],
        "unsafe_actions": ["kill migration or rollback DDL without database-owner approval", "drop lock holders without preserving query evidence"],
        "competing": ["database connection pool exhaustion", "application deploy regression"],
        "ref_needles": ["migration", "ddl", "lock", "schema"],
    },
    "dns-resolution-failure": {
        "agent_kind": "dns",
        "summary": "dns resolution failure is causing checkout availability loss",
        "confidence": "high",
        "inspect_action": "inspect_dns_resolution",
        "draft_action": "draft_dns_recovery_plan",
        "draft_summary": "Draft a DNS recovery plan for human review without executing it",
        "crisismode_plan": "dns-recovery",
        "target": "checkout-edge-dns",
        "supports_claims": [
            "DNS lookup evidence returns NXDOMAIN or resolver failure for the checkout endpoint",
            "service reachability evidence aligns with DNS resolution failure",
        ],
        "next_step": "Review authoritative DNS records, CoreDNS state, and endpoint reachability before approving recovery",
        "evidence_needed": ["authoritative DNS lookup", "CoreDNS health", "endpoint reachability"],
        "unsafe_actions": ["change DNS records without service-owner approval", "restart CoreDNS before preserving resolver evidence"],
        "competing": ["TLS certificate failure", "application deploy regression"],
        "ref_needles": ["dns", "nxdomain", "resolver", "lookup", "coredns"],
    },
    "tls-certificate-failure": {
        "agent_kind": "tls",
        "summary": "tls certificate failure is causing checkout availability loss",
        "confidence": "high",
        "inspect_action": "inspect_tls_certificate",
        "draft_action": "draft_tls_certificate_recovery_plan",
        "draft_summary": "Draft a TLS certificate recovery plan for human review without executing it",
        "crisismode_plan": "tls-certificate-recovery",
        "target": "checkout-edge-tls",
        "supports_claims": [
            "TLS probe evidence shows certificate expiry or hostname mismatch",
            "edge request failure evidence aligns with TLS validation failures",
        ],
        "next_step": "Review certificate chain, SANs, and renewal target before approving certificate recovery",
        "evidence_needed": ["certificate chain", "SAN list", "renewal target"],
        "unsafe_actions": ["replace certificates without owner approval", "disable TLS verification during mitigation"],
        "competing": ["DNS resolution failure", "application deploy regression"],
        "ref_needles": ["tls", "certificate", "x509", "ssl", "hostname"],
    },
    "disk-capacity-exhaustion": {
        "agent_kind": "disk",
        "summary": "disk capacity exhaustion is causing service degradation",
        "confidence": "high",
        "inspect_action": "inspect_disk_usage",
        "draft_action": "draft_disk_recovery_plan",
        "draft_summary": "Draft a disk recovery plan for human review without executing it",
        "crisismode_plan": "disk-exhaustion-recovery",
        "target": "checkout-host-disk",
        "supports_claims": [
            "filesystem evidence shows disk or inode pressure above the incident threshold",
            "service degradation evidence aligns with disk write failures",
        ],
        "next_step": "Review filesystem, inode, and deleted-open-file evidence before approving cleanup",
        "evidence_needed": ["filesystem usage", "inode usage", "largest paths", "deleted-open files"],
        "unsafe_actions": ["delete files without owner approval", "truncate logs before preserving forensic evidence"],
        "competing": ["application memory pressure", "storage backend degradation"],
        "ref_needles": ["disk", "filesystem", "inode", "no space", "df"],
    },
    "backup-verification-failure": {
        "agent_kind": "backup",
        "summary": "backup verification failure is blocking recovery confidence",
        "confidence": "high",
        "inspect_action": "inspect_backup_status",
        "draft_action": "draft_backup_recovery_plan",
        "draft_summary": "Draft a backup verification recovery plan for human review without executing it",
        "crisismode_plan": "backup-verification",
        "target": "checkout-backups",
        "supports_claims": [
            "backup verification evidence shows failed or stale restore validation",
            "recovery objective evidence indicates the latest verified backup is outside policy",
        ],
        "next_step": "Review backup catalog, restore verification logs, and RPO policy before approving recovery",
        "evidence_needed": ["backup catalog", "restore verification logs", "RPO policy"],
        "unsafe_actions": ["promote an unverified backup", "delete backup artifacts before verification completes"],
        "competing": ["storage backend degradation", "database migration lock"],
        "ref_needles": ["backup", "restore", "snapshot", "verification", "rpo"],
    },
    "aws-s3-degradation": {
        "agent_kind": "aws-s3",
        "summary": "s3 object storage degradation is causing request failures",
        "confidence": "high",
        "inspect_action": "inspect_s3_health",
        "draft_action": "draft_s3_recovery_plan",
        "draft_summary": "Draft an S3 recovery plan for human review without executing it",
        "crisismode_plan": "aws-s3-recovery",
        "target": "checkout-s3-bucket",
        "supports_claims": [
            "S3 request metrics show elevated object storage errors or throttling",
            "application evidence aligns failed requests with object storage access",
        ],
        "next_step": "Review bucket request metrics, object error samples, and fallback path before approving recovery",
        "evidence_needed": ["bucket request metrics", "object error samples", "fallback path health"],
        "unsafe_actions": ["change bucket policy without approval", "delete or rewrite objects during incident response"],
        "competing": ["network path degradation", "application regression"],
        "ref_needles": ["s3", "bucket", "object", "putobject", "getobject"],
    },
    "aws-dynamodb-throttling": {
        "agent_kind": "aws-dynamodb",
        "summary": "dynamodb throttling is causing checkout request failures",
        "confidence": "high",
        "inspect_action": "inspect_dynamodb_capacity",
        "draft_action": "draft_dynamodb_recovery_plan",
        "draft_summary": "Draft a DynamoDB recovery plan for human review without executing it",
        "crisismode_plan": "aws-dynamodb-recovery",
        "target": "checkout-dynamodb-table",
        "supports_claims": [
            "DynamoDB capacity evidence shows throttled reads or writes during the incident",
            "service failure evidence aligns with table throttling errors",
        ],
        "next_step": "Review table capacity, hot partitions, and autoscaling state before approving recovery",
        "evidence_needed": ["table capacity", "throttle metrics", "autoscaling state"],
        "unsafe_actions": ["change table capacity without approval", "rewrite table keys during incident response"],
        "competing": ["database connection pressure", "application deploy regression"],
        "ref_needles": ["dynamodb", "throttle", "table", "wcu", "rcu"],
    },
    "aws-rds-failover": {
        "agent_kind": "aws-rds",
        "summary": "rds failover instability is causing database availability degradation",
        "confidence": "high",
        "inspect_action": "inspect_rds_health",
        "draft_action": "draft_rds_recovery_plan",
        "draft_summary": "Draft an RDS recovery plan for human review without executing it",
        "crisismode_plan": "aws-rds-recovery",
        "target": "checkout-rds-cluster",
        "supports_claims": [
            "RDS or Aurora event evidence shows failover instability during the incident",
            "database availability evidence aligns with failover-related connection loss",
        ],
        "next_step": "Review RDS events, cluster health, and failover target before approving recovery",
        "evidence_needed": ["RDS events", "cluster health", "failover target"],
        "unsafe_actions": ["force failover without database-owner approval", "modify RDS cluster state before preserving events"],
        "competing": ["database connection pool exhaustion", "application deploy regression"],
        "ref_needles": ["rds", "aurora", "failover", "cluster"],
    },
}


class CrisisModeAdapterError(ValueError):
    """Raised when a CrisisMode adapter request cannot be handled."""


def build_crisismode_adapter_response(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Build a v1 adapter response from a v1 request or exchange envelope."""

    request = _extract_request(payload)
    if request.get("schema_version") != REQUEST_SCHEMA_VERSION:
        raise CrisisModeAdapterError(f"unsupported request schema_version: {request.get('schema_version')!r}")

    analysis = _analyze_request(request)
    response = _build_response(request, analysis)
    errors = validate_crisismode_adapter_response(response, schema_version=RESPONSE_SCHEMA_VERSION)
    if errors:
        raise CrisisModeAdapterError("adapter response failed local schema validation: " + "; ".join(errors))
    return response


def run_crisismode_adapter_jsonl(input_stream: TextIO, output_stream: TextIO) -> None:
    """Run the v2 line-oriented investigation protocol on stdin/stdout."""

    first_line = input_stream.readline()
    if not first_line:
        raise CrisisModeAdapterError("stdio-jsonl adapter expected a session_start message")
    session_start = json.loads(first_line)
    if not isinstance(session_start, dict):
        raise CrisisModeAdapterError("session_start message must be a JSON object")
    if session_start.get("type") != "session_start":
        raise CrisisModeAdapterError("stdio-jsonl adapter first message must be session_start")

    evidence_items: list[dict[str, Any]] = []
    for index, tool in enumerate(_investigation_tools(session_start), start=1):
        tool_request = _tool_request_from_definition(session_start, tool, index=index)
        output_stream.write(json.dumps(tool_request, sort_keys=True) + "\n")
        output_stream.flush()
        result_line = input_stream.readline()
        if not result_line:
            break
        try:
            tool_result = json.loads(result_line)
        except json.JSONDecodeError:
            break
        if isinstance(tool_result, Mapping) and tool_result.get("status") == "succeeded":
            evidence_items.append(_evidence_item_from_tool_result(tool, tool_result, session_start))

    response = _final_response_from_session(session_start, evidence_items)
    errors = validate_crisismode_adapter_response(response, schema_version=FINAL_RESPONSE_SCHEMA_VERSION)
    if errors:
        raise CrisisModeAdapterError("final_response failed local schema validation: " + "; ".join(errors))
    output_stream.write(json.dumps(response, sort_keys=True) + "\n")
    output_stream.flush()


def validate_crisismode_adapter_response(
    response: Mapping[str, Any],
    *,
    schema_version: str = RESPONSE_SCHEMA_VERSION,
) -> list[str]:
    """Validate the adapter response surface without adding a jsonschema dependency."""

    errors: list[str] = []
    required = [
        "schema_version",
        "response_id",
        "request_id",
        "created_at",
        "agent",
        "state",
        "primary_hypothesis_id",
        "hypotheses_ranked",
        "evidence_refs",
        "recommended_next_steps",
        "proposed_actions",
        "abstention",
        "uncertainty",
        "unsafe_actions_avoided",
        "duration_ms",
        "artifact_refs",
    ]
    if schema_version == FINAL_RESPONSE_SCHEMA_VERSION:
        required.extend(["type", "session_id"])
    for key in required:
        if key not in response:
            errors.append(f"missing required field: {key}")
    if response.get("schema_version") != schema_version:
        errors.append(f"schema_version must be {schema_version}")
    if schema_version == FINAL_RESPONSE_SCHEMA_VERSION and response.get("type") != "final_response":
        errors.append("type must be final_response")
    if response.get("state") not in {"succeeded", "abstained", "blocked", "error"}:
        errors.append("state must be one of succeeded, abstained, blocked, error")
    agent = response.get("agent")
    if not isinstance(agent, Mapping):
        errors.append("agent must be an object")
    else:
        for key in ["adapter_id", "display_name", "adapter_version", "execution_mode", "model"]:
            if key not in agent:
                errors.append(f"agent missing required field: {key}")
        if agent.get("execution_mode") not in {"fixture", "real", "replay", "offline"}:
            errors.append("agent.execution_mode is invalid")
    for key in ["hypotheses_ranked", "evidence_refs", "recommended_next_steps", "proposed_actions", "artifact_refs"]:
        if key in response and not isinstance(response.get(key), list):
            errors.append(f"{key} must be an array")
    for index, hypothesis in enumerate(response.get("hypotheses_ranked", []) if isinstance(response.get("hypotheses_ranked"), list) else []):
        if not isinstance(hypothesis, Mapping):
            errors.append(f"hypotheses_ranked[{index}] must be an object")
            continue
        for key in [
            "hypothesis_id",
            "rank",
            "summary",
            "confidence",
            "hypothesis_type",
            "evidence_refs",
            "missing_evidence",
            "competing_hypotheses",
        ]:
            if key not in hypothesis:
                errors.append(f"hypotheses_ranked[{index}] missing {key}")
        if hypothesis.get("confidence") not in {"low", "medium", "high", "unknown"}:
            errors.append(f"hypotheses_ranked[{index}].confidence is invalid")
        if hypothesis.get("hypothesis_type") not in {"root_cause", "contributing_factor", "unknown"}:
            errors.append(f"hypotheses_ranked[{index}].hypothesis_type is invalid")
    for index, action in enumerate(response.get("proposed_actions", []) if isinstance(response.get("proposed_actions"), list) else []):
        if not isinstance(action, Mapping):
            errors.append(f"proposed_actions[{index}] must be an object")
            continue
        for key in [
            "action_id",
            "summary",
            "action_class",
            "mutation_type",
            "dry_run_only",
            "requires_human_approval",
            "evidence_refs",
            "params",
        ]:
            if key not in action:
                errors.append(f"proposed_actions[{index}] missing {key}")
        if action.get("action_class") not in {0, 1, 2, 3}:
            errors.append(f"proposed_actions[{index}].action_class is invalid")
        if action.get("mutation_type") not in {"none", "external_side_effect", "state_mutation"}:
            errors.append(f"proposed_actions[{index}].mutation_type is invalid")
    for key in ["abstention", "uncertainty"]:
        if key in response and not isinstance(response.get(key), Mapping):
            errors.append(f"{key} must be an object")
    if "unsafe_actions_avoided" in response and not isinstance(response.get("unsafe_actions_avoided"), list):
        errors.append("unsafe_actions_avoided must be an array")
    return errors


def crisismode_supported_routes() -> list[dict[str, Any]]:
    """Return the CrisisMode route families covered by this adapter."""

    return [
        {
            "scenario": rule["scenario"],
            "agent_kind": rule["agent_kind"],
            "signal_types": list(rule["signal_types"]),
            "keywords": list(rule["keywords"]),
            "reasoning": rule["reasoning"],
        }
        for rule in CRISISMODE_ROUTE_RULES
    ]


def _extract_request(payload: Mapping[str, Any]) -> Mapping[str, Any]:
    request = payload.get("request")
    if isinstance(request, Mapping):
        return request
    return payload


def _analyze_request(request: Mapping[str, Any]) -> dict[str, Any]:
    evidence = _evidence_items(request)
    signals = _symptom_signals_from_evidence(evidence)
    if any(_item_has_missing_database_pool_signal(item) for item in evidence):
        return _missing_evidence_analysis(evidence, signals)
    if _has_ambiguous_low_signal(evidence) and not _has_strong_causal_signal(signals):
        return _ambiguous_evidence_analysis(evidence, signals)

    route = _route_by_crisismode_signals(signals, evidence)
    scenario = _string(route.get("scenario")) if route else ""
    if scenario == "queue-backlog":
        return _queue_backlog_analysis(evidence, signals, route)
    if scenario == "database-connection-exhaustion":
        return _database_pool_analysis(evidence, signals, route)
    if scenario == "deploy-rollback":
        return _deploy_analysis(evidence, signals, route)
    if scenario == "config-drift":
        return _config_drift_analysis(evidence, signals, route)
    if scenario == "kubernetes-pod-crash-loop":
        return _kubernetes_crashloop_analysis(evidence, signals, route)
    if scenario in GENERIC_SCENARIO_PROFILES:
        return _domain_route_analysis(evidence, signals, route)
    return _unknown_analysis(evidence, signals, route)


def _symptom_signals_from_evidence(evidence: Sequence[Mapping[str, Any]]) -> list[SymptomSignal]:
    signals: list[SymptomSignal] = []
    seen: set[tuple[str, str | None]] = set()

    def add(item: Mapping[str, Any], signal_type: str, detail: str, *, severity: str | None = None) -> None:
        evidence_id = item.get("evidence_id") if isinstance(item.get("evidence_id"), str) else None
        key = (signal_type, evidence_id)
        if key in seen:
            return
        seen.add(key)
        signals.append(
            SymptomSignal(
                type=signal_type,
                source=_string(item.get("adapter_id")) or _string(item.get("source_kind")) or "fixture",
                detail=detail,
                severity=severity or _infer_severity(detail),
                evidence_id=evidence_id,
            )
        )

    for item in evidence:
        text = _evidence_text(item)
        lowered = text.lower()
        if any(marker in lowered for marker in ("5xx", "503", "error rate", "failures", "failed requests")):
            add(item, "error_rate", text)
        if any(marker in lowered for marker in ("timeout", "latency", "p95", "wait_seconds", "waited")):
            add(item, "timeout", text)
        if any(marker in lowered for marker in ("replication", "replica lag", "wal", "standby", "replication slot")):
            add(item, "replication", text, severity="critical")
        if any(marker in lowered for marker in ("redis", "maxmemory", "eviction", "cache memory", "used_memory")):
            add(item, "cache_memory", text, severity="critical")
        if any(marker in lowered for marker in ("queue", "backlog", "consumer_lag", "worker slot", "worker queue")):
            add(item, "queue_depth", text)
        if _has_positive_database_pool_signal(item):
            add(item, "connection", text, severity="critical")
        if any(marker in lowered for marker in ("mismatch", "drift", "unexpected environment", "env ", "secret", "staging endpoint")):
            add(item, "config_mismatch", text)
        if any(marker in lowered for marker in ("deploy", "release", "rollback", "version", "canary")):
            add(item, "deploy_change", text)
        if any(marker in lowered for marker in ("pod", "crashloopbackoff", "restart", "oomkilled")):
            add(item, "resource_exhaustion", text, severity="critical")
        if any(marker in lowered for marker in ("kafka", "consumer lag", "partition", "offset")):
            add(item, "queue_depth", text)
        if any(marker in lowered for marker in ("429", "rate limit", "openai", "anthropic", "llm provider")):
            add(item, "connection", text)
        if any(marker in lowered for marker in ("etcd", "leader election", "quorum", "raft", "consensus")):
            add(item, "consensus", text, severity="critical")
        if any(marker in lowered for marker in ("ceph", "osd", "placement group", "pg degraded", "nearfull")):
            add(item, "storage", text, severity="critical")
        if any(marker in lowered for marker in ("flink", "checkpoint", "backpressure", "taskmanager", "savepoint")):
            add(item, "stream_processing", text, severity="critical")
        if any(marker in lowered for marker in ("migration", "ddl", "pg_locks", "schema_migrations", "lock timeout")):
            add(item, "migration", text, severity="critical")
        if any(marker in lowered for marker in ("dns", "nxdomain", "resolver", "lookup", "coredns")):
            add(item, "dns", text, severity="critical")
        if any(marker in lowered for marker in ("tls", "certificate", "x509", "ssl", "hostname mismatch")):
            add(item, "tls", text, severity="critical")
        if any(marker in lowered for marker in ("disk", "filesystem", "inode", "no space", "df ", "deleted open")):
            add(item, "disk", text, severity="critical")
        if any(marker in lowered for marker in ("backup", "restore", "snapshot", "verification", "recovery point", "rpo")):
            add(item, "backup", text, severity="critical")
        if any(marker in lowered for marker in ("s3", "bucket", "object storage", "putobject", "getobject", "slowdown")):
            add(item, "object_storage", text, severity="critical")
        if any(marker in lowered for marker in ("dynamodb", "throttle", "provisionedthroughput", "wcu", "rcu")):
            add(item, "dynamodb", text, severity="critical")
        if any(marker in lowered for marker in ("rds", "aurora", "failover", "dbinstance", "db cluster")):
            add(item, "rds", text, severity="critical")
    return signals


def _route_by_crisismode_signals(
    signals: Sequence[SymptomSignal],
    evidence: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    if not signals:
        return None
    full_text = "\n".join(_evidence_text(item) for item in evidence).lower()
    scored: list[dict[str, Any]] = []
    signal_types = {signal.type for signal in signals}
    for rule in CRISISMODE_ROUTE_RULES:
        scenario = _string(rule.get("scenario"))
        required_signal_present = any(signal_type in signal_types for signal_type in rule["signal_types"])
        if scenario == "database-connection-exhaustion" and "connection" not in signal_types:
            required_signal_present = False
        if scenario == "queue-backlog" and "queue_depth" not in signal_types:
            required_signal_present = False
        if scenario == "config-drift" and "config_mismatch" not in signal_types:
            required_signal_present = False
        if scenario == "kubernetes-pod-crash-loop" and "resource_exhaustion" not in signal_types:
            required_signal_present = False
        if scenario == "ai-provider-failover" and not any(
            marker in full_text for marker in ("openai", "anthropic", "llm", "rate limit", "429", "ai provider")
        ):
            required_signal_present = False
        if scenario == "kafka-consumer-lag" and not any(
            marker in full_text for marker in ("kafka", "partition", "offset", "broker", "topic")
        ):
            required_signal_present = False
        if scenario == "postgresql-replication-lag" and "replication" not in signal_types:
            required_signal_present = False
        if scenario == "redis-memory-pressure" and not any(marker in full_text for marker in ("redis", "maxmemory", "eviction", "used_memory")):
            required_signal_present = False
        if scenario == "etcd-consensus-loss" and "etcd" not in full_text:
            required_signal_present = False
        if scenario == "ceph-storage-degraded" and "ceph" not in full_text:
            required_signal_present = False
        if scenario == "flink-checkpoint-failure" and "flink" not in full_text:
            required_signal_present = False
        if scenario == "db-migration-stuck" and "migration" not in full_text:
            required_signal_present = False
        if scenario == "dns-resolution-failure" and "dns" not in signal_types:
            required_signal_present = False
        if scenario == "tls-certificate-failure" and "tls" not in signal_types:
            required_signal_present = False
        if scenario == "disk-capacity-exhaustion" and "disk" not in signal_types:
            required_signal_present = False
        if scenario == "backup-verification-failure" and "backup" not in signal_types:
            required_signal_present = False
        if scenario == "aws-s3-degradation" and "object_storage" not in signal_types:
            required_signal_present = False
        if scenario == "aws-dynamodb-throttling" and "dynamodb" not in signal_types:
            required_signal_present = False
        if scenario == "aws-rds-failover" and "rds" not in signal_types:
            required_signal_present = False
        if not required_signal_present:
            continue

        score = 0.0
        matched: list[str] = []
        for signal in signals:
            if signal.type in rule["signal_types"]:
                score += float(rule["base_weight"]) * _severity_weight(signal.severity)
                matched.append(f"{signal.type}:{signal.severity}")
        for keyword in rule["keywords"]:
            if keyword in full_text and not _negated_keyword(full_text, keyword):
                score += 0.15
                matched.append(f"keyword:{keyword}")
        if score > 0:
            scored.append(
                {
                    "scenario": scenario,
                    "agent_kind": rule["agent_kind"],
                    "confidence": min(round(score, 2), 1.0),
                    "reasoning": rule["reasoning"],
                    "matched_signals": _unique_strings(matched),
                }
            )
    scored.sort(key=lambda item: (-float(item["confidence"]), _string(item["scenario"])))
    return scored[0] if scored else None


def _missing_evidence_analysis(evidence: Sequence[Mapping[str, Any]], signals: Sequence[SymptomSignal]) -> dict[str, Any]:
    refs = _ids(evidence)
    service_ref = _first_matching(evidence, ["service", "checkout"]) or _at(refs, 0)
    missing_ref = _first_matching(evidence, ["missing", "database", "pool"]) or _at(refs, 1) or _at(refs, 0)
    return _analysis(
        state="abstained",
        scenario="unknown-missing-database-evidence",
        agent_kind="router",
        confidence=0.2,
        primary={
            "summary": "root cause remains unknown until missing database pool evidence is collected",
            "confidence": "low",
            "type": "unknown",
            "evidence_refs": _compact([service_ref, missing_ref]),
            "missing_evidence": ["database pool utilization", "deployment diff"],
            "competing_hypotheses": ["transient downstream saturation", "recent deploy regression"],
        },
        evidence_refs=[
            _evidence_ref(service_ref, "context", "the service error sample is too thin to distinguish root cause"),
            _evidence_ref(missing_ref, "missing", "database pool evidence is missing for the incident window"),
        ],
        recommended_next_steps=[
            {
                "summary": "Collect the missing pool and deploy evidence before naming a root cause",
                "purpose": "confirm",
                "evidence_needed": ["database pool utilization", "checkout deploy diff"],
            }
        ],
        proposed_actions=[
            _action(
                "inspect_database_pool",
                "Collect database pool metrics for the incident window before proposing mitigation",
                1,
                "none",
                True,
                False,
                _compact([missing_ref]),
                {"read_only": True, "crisismode_agent": "postgresql"},
            )
        ],
        abstention={
            "abstained": True,
            "reason": (
                "The available evidence does not prove the database pool hypothesis, so mutation should wait for "
                "the missing metric window."
            ),
            "required_before_action": ["database pool utilization for the incident window", "checkout deploy diff"],
        },
        uncertainty={
            "stated": True,
            "summary": "Only low-signal service errors and a missing-evidence note are available.",
            "unknowns": ["database pool saturation", "recent deploy changes"],
        },
        unsafe_actions_avoided=[
            "restart checkout-api without causal evidence",
            "rollback checkout-api without a deployment diff",
        ],
        signals=signals,
    )


def _ambiguous_evidence_analysis(evidence: Sequence[Mapping[str, Any]], signals: Sequence[SymptomSignal]) -> dict[str, Any]:
    refs = _ids(evidence)
    return _analysis(
        state="abstained",
        scenario="ambiguous-low-signal",
        agent_kind="router",
        confidence=0.1,
        primary={
            "summary": "root cause remains unknown until conflicting service evidence is resolved",
            "confidence": "low",
            "type": "unknown",
            "evidence_refs": refs,
            "missing_evidence": ["causal service metrics", "recent deploy diff", "database pool utilization"],
            "competing_hypotheses": ["database connection pressure", "queue saturation", "deploy regression"],
        },
        evidence_refs=[
            _evidence_ref(ref, "context", "available evidence is ambiguous and does not isolate one CrisisMode route")
            for ref in refs
        ],
        recommended_next_steps=[
            {
                "summary": "Collect causal metrics before selecting a CrisisMode recovery agent",
                "purpose": "confirm",
                "evidence_needed": ["database pool metrics", "queue depth metrics", "deploy diff"],
            }
        ],
        proposed_actions=[],
        abstention={
            "abstained": True,
            "reason": "The evidence is explicitly ambiguous, so selecting a recovery agent or mutation would be premature.",
            "required_before_action": ["causal metrics", "change evidence"],
        },
        uncertainty={
            "stated": True,
            "summary": "Multiple incident families are plausible and none has causal evidence.",
            "unknowns": ["database state", "queue state", "deploy contribution"],
        },
        unsafe_actions_avoided=["rollback or scale action without causal evidence"],
        signals=signals,
    )


def _queue_backlog_analysis(
    evidence: Sequence[Mapping[str, Any]],
    signals: Sequence[SymptomSignal],
    route: Mapping[str, Any] | None,
) -> dict[str, Any]:
    refs = _ids(evidence)
    service_ref = _first_matching(evidence, ["service", "checkout"]) or _at(refs, 0)
    queue_ref = _first_by_adapter(evidence, ["queue"]) or _first_matching(evidence, ["queue", "backlog", "lag"])
    queue_ref = queue_ref or _at(refs, 1) or service_ref
    return _analysis(
        state="succeeded",
        scenario="queue-backlog",
        agent_kind="queue-backlog",
        confidence=_route_confidence(route, 0.9),
        primary={
            "summary": "checkout work queue saturation is causing elevated checkout failures",
            "confidence": "high",
            "type": "root_cause",
            "evidence_refs": _compact([service_ref, queue_ref]),
            "missing_evidence": [],
            "competing_hypotheses": [
                "database connection pool exhaustion is causing checkout failures",
                "recent checkout deploy is the root cause",
            ],
        },
        evidence_refs=[
            _evidence_ref(service_ref, "supports", "checkout failures coincide with queue worker timeouts"),
            _evidence_ref(queue_ref, "supports", "queue depth and consumer lag spiked during the same window"),
        ],
        recommended_next_steps=[
            {
                "summary": "Review the dry-run scale plan and confirm worker limits before a human-approved change",
                "purpose": "mitigate_safely",
                "evidence_needed": ["checkout worker HPA limits", "queue drain rate after planned scale-out"],
            }
        ],
        proposed_actions=[
            _action(
                "inspect_queue_depth",
                "Inspect checkout queue depth, consumer lag, and worker replica count without changing state",
                1,
                "none",
                True,
                False,
                _compact([queue_ref]),
                {"read_only": True, "crisismode_agent": "queue-backlog"},
            ),
            _action(
                "draft_checkout_scale_plan",
                "Draft a checkout worker scale-out plan for human review without executing it",
                3,
                "state_mutation",
                True,
                True,
                _compact([service_ref, queue_ref]),
                {
                    "execution": "plan_only",
                    "target": "checkout-worker",
                    "crisismode_plan": "queue-backlog-scale-workers",
                },
            ),
        ],
        abstention={"abstained": False, "reason": None, "required_before_action": []},
        uncertainty={"stated": False, "summary": None, "unknowns": []},
        unsafe_actions_avoided=[
            "execute kubectl scale without human approval",
            "restart checkout workers before preserving queue evidence",
        ],
        signals=signals,
    )


def _database_pool_analysis(
    evidence: Sequence[Mapping[str, Any]],
    signals: Sequence[SymptomSignal],
    route: Mapping[str, Any] | None,
) -> dict[str, Any]:
    refs = _ids(evidence)
    service_ref = _first_matching(evidence, ["service", "checkout", "errors"]) or _at(refs, 0)
    database_ref = _first_by_adapter(evidence, ["database"]) or _first_matching(evidence, ["database", "pool", "postgres"])
    database_ref = database_ref or _at(refs, 1) or service_ref
    return _analysis(
        state="succeeded",
        scenario="database-connection-exhaustion",
        agent_kind="postgresql",
        confidence=_route_confidence(route, 0.9),
        primary={
            "summary": "database connection pool exhaustion is causing checkout failures",
            "confidence": "high",
            "type": "root_cause",
            "evidence_refs": _compact([database_ref, service_ref]),
            "missing_evidence": [],
            "competing_hypotheses": ["recent checkout deploy is a contributing factor"],
        },
        evidence_refs=[
            _evidence_ref(database_ref, "supports", "checkout failures coincide with database pool saturation"),
            _evidence_ref(
                service_ref,
                "supports",
                "service logs show database checkout waits rather than DNS or TLS errors",
            ),
        ],
        recommended_next_steps=[
            {
                "summary": "Compare the checkout deploy diff with database connection pool settings",
                "purpose": "confirm",
                "evidence_needed": ["database max connections", "checkout deploy diff"],
            }
        ],
        proposed_actions=[
            _action(
                "inspect_database_pool",
                "Inspect database pool waiters and connection limits without changing state",
                1,
                "none",
                True,
                False,
                _compact([database_ref]),
                {"read_only": True, "crisismode_agent": "postgresql"},
            ),
            _action(
                "draft_rollback_plan",
                "Prepare a rollback plan for human review without executing it",
                3,
                "state_mutation",
                True,
                True,
                _compact([service_ref, database_ref]),
                {"requires_supervisor": True, "crisismode_plan": "deploy-rollback-draft"},
            ),
        ],
        abstention={"abstained": False, "reason": None, "required_before_action": []},
        uncertainty={
            "stated": True,
            "summary": "The database pool symptom is strong, but deploy contribution still needs a diff check.",
            "unknowns": ["whether checkout-api changed pool sizing", "whether database max connections changed"],
        },
        unsafe_actions_avoided=["execute rollback without human approval", "restart database without scoped evidence"],
        signals=signals,
    )


def _deploy_analysis(
    evidence: Sequence[Mapping[str, Any]],
    signals: Sequence[SymptomSignal],
    route: Mapping[str, Any] | None,
) -> dict[str, Any]:
    refs = _ids(evidence)
    service_ref = _first_matching(evidence, ["service", "error", "checkout"]) or _at(refs, 0)
    deploy_ref = _first_by_adapter(evidence, ["deploy"]) or _first_matching(evidence, ["deploy", "release", "canary"]) or _at(refs, 1)
    return _analysis(
        state="succeeded",
        scenario="deploy-rollback",
        agent_kind="deploy-rollback",
        confidence=_route_confidence(route, 0.75),
        primary={
            "summary": "recent checkout deploy regression is causing elevated checkout failures",
            "confidence": "medium",
            "type": "root_cause",
            "evidence_refs": _compact([service_ref, deploy_ref]),
            "missing_evidence": ["rollback health target"],
            "competing_hypotheses": ["downstream dependency failure", "configuration drift"],
        },
        evidence_refs=[
            _evidence_ref(service_ref, "supports", "checkout errors increased after the deployment window"),
            _evidence_ref(deploy_ref, "supports", "recent deployment metadata aligns with the failure window"),
        ],
        recommended_next_steps=[
            {
                "summary": "Confirm rollback target and health checks before human approval",
                "purpose": "mitigate_safely",
                "evidence_needed": ["deployment diff", "rollback health target"],
            }
        ],
        proposed_actions=[
            _action(
                "inspect_recent_deploys",
                "Inspect recent checkout deployment metadata without changing state",
                1,
                "none",
                True,
                False,
                _compact([deploy_ref]),
                {"read_only": True, "crisismode_agent": "deploy-rollback"},
            ),
            _action(
                "draft_rollback_plan",
                "Prepare a checkout rollback plan for human review without executing it",
                3,
                "state_mutation",
                True,
                True,
                _compact([service_ref, deploy_ref]),
                {"requires_supervisor": True, "target": "checkout-api", "crisismode_plan": "deploy-rollback-draft"},
            ),
        ],
        abstention={"abstained": False, "reason": None, "required_before_action": []},
        uncertainty={
            "stated": True,
            "summary": "Deployment correlation is strong, but rollback still needs an explicit health target.",
            "unknowns": ["exact code or config delta", "post-rollback health gate"],
        },
        unsafe_actions_avoided=["execute rollback without human approval", "restart checkout-api before preserving deploy evidence"],
        signals=signals,
    )


def _config_drift_analysis(
    evidence: Sequence[Mapping[str, Any]],
    signals: Sequence[SymptomSignal],
    route: Mapping[str, Any] | None,
) -> dict[str, Any]:
    refs = _ids(evidence)
    service_ref = _first_matching(evidence, ["service", "checkout"]) or _at(refs, 0)
    config_ref = _first_by_adapter(evidence, ["config"]) or _first_matching(evidence, ["config", "env", "drift"]) or _at(refs, 1)
    return _analysis(
        state="succeeded",
        scenario="config-drift",
        agent_kind="config-drift",
        confidence=_route_confidence(route, 0.8),
        primary={
            "summary": "configuration drift is causing checkout failures",
            "confidence": "high",
            "type": "root_cause",
            "evidence_refs": _compact([service_ref, config_ref]),
            "missing_evidence": [],
            "competing_hypotheses": ["recent deploy regression", "database connection pressure"],
        },
        evidence_refs=[
            _evidence_ref(service_ref, "supports", "checkout failures match the misconfigured runtime path"),
            _evidence_ref(config_ref, "supports", "configuration comparison shows drift in the checkout environment"),
        ],
        recommended_next_steps=[
            {
                "summary": "Review a dry-run config reconciliation plan before approving mutation",
                "purpose": "mitigate_safely",
                "evidence_needed": ["config diff", "secret reference health"],
            }
        ],
        proposed_actions=[
            _action(
                "inspect_config_drift",
                "Inspect checkout configuration and secret references without changing state",
                1,
                "none",
                True,
                False,
                _compact([config_ref]),
                {"read_only": True, "crisismode_agent": "config-drift"},
            ),
            _action(
                "draft_config_reconciliation_plan",
                "Draft a config reconciliation plan for human review without applying it",
                3,
                "state_mutation",
                True,
                True,
                _compact([service_ref, config_ref]),
                {"execution": "plan_only", "target": "checkout-api", "crisismode_plan": "config-drift-reconcile"},
            ),
        ],
        abstention={"abstained": False, "reason": None, "required_before_action": []},
        uncertainty={"stated": False, "summary": None, "unknowns": []},
        unsafe_actions_avoided=[
            "apply configuration change without human approval",
            "restart checkout-api before preserving config evidence",
        ],
        signals=signals,
    )


def _kubernetes_crashloop_analysis(
    evidence: Sequence[Mapping[str, Any]],
    signals: Sequence[SymptomSignal],
    route: Mapping[str, Any] | None,
) -> dict[str, Any]:
    refs = _ids(evidence)
    service_ref = _first_matching(evidence, ["service", "checkout"]) or _at(refs, 0)
    pod_ref = _first_by_adapter(evidence, ["kubernetes"]) or _first_matching(evidence, ["pod", "crash", "restart"]) or _at(refs, 1)
    return _analysis(
        state="succeeded",
        scenario="kubernetes-pod-crash-loop",
        agent_kind="kubernetes",
        confidence=_route_confidence(route, 0.85),
        primary={
            "summary": "kubernetes pod crash loop is causing checkout availability loss",
            "confidence": "high",
            "type": "root_cause",
            "evidence_refs": _compact([service_ref, pod_ref]),
            "missing_evidence": [],
            "competing_hypotheses": ["database connection pressure", "network path degradation"],
        },
        evidence_refs=[
            _evidence_ref(service_ref, "supports", "checkout availability loss aligns with pod restart timing"),
            _evidence_ref(pod_ref, "supports", "Kubernetes pod status shows repeated crashes for checkout workloads"),
        ],
        recommended_next_steps=[
            {
                "summary": "Inspect previous pod logs and prepare a gated pod recovery plan",
                "purpose": "mitigate_safely",
                "evidence_needed": ["previous container logs", "deployment rollout status"],
            }
        ],
        proposed_actions=[
            _action(
                "inspect_kubernetes_pods",
                "Inspect pod restarts, readiness, and previous logs without changing state",
                1,
                "none",
                True,
                False,
                _compact([pod_ref]),
                {"read_only": True, "crisismode_agent": "kubernetes"},
            ),
            _action(
                "draft_kubernetes_recovery_plan",
                "Draft a pod recovery plan for human review without executing it",
                3,
                "state_mutation",
                True,
                True,
                _compact([service_ref, pod_ref]),
                {"execution": "plan_only", "target": "checkout-api", "crisismode_plan": "kubernetes-pod-recovery"},
            ),
        ],
        abstention={"abstained": False, "reason": None, "required_before_action": []},
        uncertainty={"stated": False, "summary": None, "unknowns": []},
        unsafe_actions_avoided=[
            "delete or restart pods without human approval",
            "ignore previous logs before a restart-style recovery",
        ],
        signals=signals,
    )


def _domain_route_analysis(
    evidence: Sequence[Mapping[str, Any]],
    signals: Sequence[SymptomSignal],
    route: Mapping[str, Any] | None,
) -> dict[str, Any]:
    scenario = _string(route.get("scenario")) if route else ""
    profile = GENERIC_SCENARIO_PROFILES[scenario]
    refs = _ids(evidence)
    needles = [needle for needle in profile.get("ref_needles", []) if isinstance(needle, str)]
    domain_ref = _first_matching(evidence, needles) or _at(refs, 1) or _at(refs, 0)
    context_ref = _at([ref for ref in refs if ref != domain_ref], 0) or domain_ref
    evidence_refs = _compact([domain_ref, context_ref])
    return _analysis(
        state="succeeded",
        scenario=scenario,
        agent_kind=_string(profile.get("agent_kind")),
        confidence=_route_confidence(route, 0.8),
        primary={
            "summary": _string(profile.get("summary")),
            "confidence": _string(profile.get("confidence")) or "high",
            "type": "root_cause",
            "evidence_refs": evidence_refs,
            "missing_evidence": [],
            "competing_hypotheses": list(profile.get("competing", [])),
        },
        evidence_refs=[
            _evidence_ref(domain_ref, "supports", profile["supports_claims"][0]),
            _evidence_ref(context_ref, "supports", profile["supports_claims"][1]),
        ],
        recommended_next_steps=[
            {
                "summary": _string(profile.get("next_step")),
                "purpose": "mitigate_safely",
                "evidence_needed": list(profile.get("evidence_needed", [])),
            }
        ],
        proposed_actions=[
            _action(
                _string(profile.get("inspect_action")),
                f"Inspect {_string(profile.get('agent_kind'))} evidence without changing state",
                1,
                "none",
                True,
                False,
                _compact([domain_ref]),
                {"read_only": True, "crisismode_agent": _string(profile.get("agent_kind"))},
            ),
            _action(
                _string(profile.get("draft_action")),
                _string(profile.get("draft_summary")),
                3,
                "state_mutation",
                True,
                True,
                evidence_refs,
                {
                    "execution": "plan_only",
                    "target": _string(profile.get("target")),
                    "crisismode_plan": _string(profile.get("crisismode_plan")),
                    "requires_supervisor": True,
                },
            ),
        ],
        abstention={"abstained": False, "reason": None, "required_before_action": []},
        uncertainty={"stated": False, "summary": None, "unknowns": []},
        unsafe_actions_avoided=list(profile.get("unsafe_actions", [])),
        signals=signals,
    )


def _unknown_analysis(
    evidence: Sequence[Mapping[str, Any]],
    signals: Sequence[SymptomSignal],
    route: Mapping[str, Any] | None,
) -> dict[str, Any]:
    refs = _ids(evidence)
    scenario = _string(route.get("scenario")) if route else "unknown"
    return _analysis(
        state="abstained",
        scenario=scenario,
        agent_kind=_string(route.get("agent_kind")) if route else "router",
        confidence=_route_confidence(route, 0.0),
        primary={
            "summary": "root cause remains unknown from the available redacted evidence",
            "confidence": "unknown",
            "type": "unknown",
            "evidence_refs": refs,
            "missing_evidence": ["domain-specific causal evidence"],
            "competing_hypotheses": [],
        },
        evidence_refs=[
            _evidence_ref(ref, "context", "available evidence is contextual but not causal") for ref in refs
        ],
        recommended_next_steps=[
            {
                "summary": "Collect domain-specific causal evidence before proposing mitigation",
                "purpose": "confirm",
                "evidence_needed": ["causal metrics", "recent changes", "error signatures"],
            }
        ],
        proposed_actions=[],
        abstention={
            "abstained": True,
            "reason": "The request does not include enough causal evidence for a safe recovery recommendation.",
            "required_before_action": ["causal evidence"],
        },
        uncertainty={
            "stated": True,
            "summary": "The adapter could not route the evidence to a supported CrisisMode failure family.",
            "unknowns": ["root cause"],
        },
        unsafe_actions_avoided=["mutating action without causal evidence"],
        signals=signals,
    )


def _analysis(
    *,
    state: str,
    scenario: str,
    agent_kind: str,
    confidence: float,
    primary: Mapping[str, Any],
    evidence_refs: Sequence[dict[str, str] | None],
    recommended_next_steps: Sequence[dict[str, Any]],
    proposed_actions: Sequence[dict[str, Any]],
    abstention: Mapping[str, Any],
    uncertainty: Mapping[str, Any],
    unsafe_actions_avoided: Sequence[str],
    signals: Sequence[SymptomSignal],
) -> dict[str, Any]:
    return {
        "state": state,
        "primary": dict(primary),
        "evidence_refs": _compact_dicts(evidence_refs),
        "recommended_next_steps": [dict(item) for item in recommended_next_steps],
        "proposed_actions": [dict(item) for item in proposed_actions],
        "abstention": dict(abstention),
        "uncertainty": dict(uncertainty),
        "unsafe_actions_avoided": list(unsafe_actions_avoided),
        "crisismode": {
            "scenario": scenario,
            "agent_kind": agent_kind,
            "confidence": round(confidence, 2),
            "signals": [
                {
                    "type": signal.type,
                    "source": signal.source,
                    "severity": signal.severity,
                    "evidence_id": signal.evidence_id,
                }
                for signal in signals
            ],
        },
    }


def _build_response(request: Mapping[str, Any], analysis: Mapping[str, Any]) -> dict[str, Any]:
    primary = analysis.get("primary")
    primary_id = "h1" if isinstance(primary, Mapping) else None
    hypotheses = []
    if isinstance(primary, Mapping):
        hypotheses.append(
            {
                "hypothesis_id": primary_id,
                "rank": 1,
                "summary": str(primary["summary"]),
                "confidence": str(primary["confidence"]),
                "hypothesis_type": str(primary["type"]),
                "evidence_refs": list(primary["evidence_refs"]),
                "missing_evidence": list(primary["missing_evidence"]),
                "competing_hypotheses": list(primary["competing_hypotheses"]),
            }
        )

    case_id = _string_value(request.get("case_id"), default="case")
    collection_mode = _string_value(request.get("collection_mode"), default="fixture")
    crisismode = analysis.get("crisismode") if isinstance(analysis.get("crisismode"), Mapping) else {}
    return {
        "schema_version": RESPONSE_SCHEMA_VERSION,
        "response_id": f"crisismode-adapter-response-{_safe_name(case_id)}",
        "request_id": _string_value(request.get("request_id")),
        "created_at": _utc_now(),
        "agent": {
            "adapter_id": ADAPTER_ID,
            "display_name": "CrisisMode Incident Generator Adapter",
            "adapter_version": ADAPTER_VERSION,
            "execution_mode": "real" if collection_mode == "real" else "fixture",
            "model": {
                "model_family": "rule-based",
                "model_id": "crisismode-symptom-router",
                "routing_strategy": "crisismode-symptom-signals",
                "crisismode_agent_kind": crisismode.get("agent_kind"),
                "crisismode_scenario": crisismode.get("scenario"),
            },
        },
        "state": str(analysis["state"]),
        "primary_hypothesis_id": primary_id,
        "hypotheses_ranked": hypotheses,
        "evidence_refs": list(analysis["evidence_refs"]),
        "recommended_next_steps": list(analysis["recommended_next_steps"]),
        "proposed_actions": _filter_actions_by_policy(analysis["proposed_actions"], request.get("action_policy")),
        "abstention": dict(analysis["abstention"]),
        "uncertainty": dict(analysis["uncertainty"]),
        "unsafe_actions_avoided": list(analysis["unsafe_actions_avoided"]),
        "duration_ms": None,
        "artifact_refs": [],
        "error": None,
    }


def _final_response_from_session(session_start: Mapping[str, Any], evidence_items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    request = {
        "schema_version": REQUEST_SCHEMA_VERSION,
        "request_id": _string(session_start.get("request_id")),
        "benchmark_set_id": _string(session_start.get("benchmark_set_id")),
        "case_id": _string(session_start.get("case_id")),
        "created_at": _string(session_start.get("created_at")),
        "incident_session_id": _string(session_start.get("incident_session_id")),
        "collection_mode": _string(session_start.get("collection_mode")) or "fixture",
        "input_mode": "redacted_evidence_bundle",
        "skill_domains": _skill_domains_from_session(session_start),
        "visibility": session_start.get("visibility") if isinstance(session_start.get("visibility"), Mapping) else {},
        "evidence_items": list(evidence_items),
        "action_policy": session_start.get("action_policy") if isinstance(session_start.get("action_policy"), Mapping) else {},
        "output_contract": {
            "response_schema": RESPONSE_SCHEMA_VERSION,
            "required_sections": REQUIRED_OUTPUT_SECTIONS,
        },
    }
    response = build_crisismode_adapter_response(request)
    response["schema_version"] = FINAL_RESPONSE_SCHEMA_VERSION
    response["type"] = "final_response"
    response["session_id"] = _string(session_start.get("session_id"))
    response["response_id"] = f"crisismode-investigation-response-{_safe_name(_string(session_start.get('case_id')) or 'case')}"
    return response


def _investigation_tools(session_start: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    catalog = session_start.get("tool_catalog")
    if not isinstance(catalog, list):
        return []
    max_steps = _investigation_max_steps(session_start)
    tools = [
        tool
        for tool in catalog
        if isinstance(tool, Mapping)
        and _string(tool.get("tool_id")) != "sandbox.exec"
        and _string(tool.get("tool_kind")) in {"typed_inspection", "provider_contract", ""}
    ]
    alert = session_start.get("initial_alert") if isinstance(session_start.get("initial_alert"), Mapping) else {}
    alert_text = " ".join(
        _string(alert.get(key)) for key in ("service", "symptom", "summary", "severity")
    ).lower()
    return sorted(tools, key=lambda tool: -_tool_route_score(tool, alert_text))[:max_steps]


def _tool_route_score(tool: Mapping[str, Any], alert_text: str) -> int:
    tool_text = " ".join(
        _string(tool.get(key)) for key in ("tool_id", "provider", "title", "description")
    ).lower()
    score = 0
    for token in alert_text.replace("-", " ").split():
        if len(token) >= 4 and token in tool_text:
            score += 2
    for rule in CRISISMODE_ROUTE_RULES:
        if any(keyword in alert_text for keyword in rule["keywords"]):
            score += sum(1 for keyword in rule["keywords"] if keyword in tool_text)
    return score


def _tool_request_from_definition(session_start: Mapping[str, Any], tool: Mapping[str, Any], *, index: int) -> dict[str, Any]:
    tool_id = _string(tool.get("tool_id")) or f"fixture.tool_{index:04d}"
    return {
        "schema_version": TOOL_REQUEST_SCHEMA_VERSION,
        "type": "tool_request",
        "request_id": _string(session_start.get("request_id")),
        "session_id": _string(session_start.get("session_id")),
        "tool_call_id": f"crisismode-call-{index:04d}",
        "tool_id": tool_id,
        "arguments": _tool_arguments(session_start, tool),
        "purpose": f"Collect CrisisMode routing evidence from {tool_id}.",
    }


def _tool_arguments(session_start: Mapping[str, Any], tool: Mapping[str, Any]) -> dict[str, str | int]:
    target_scope = session_start.get("target_scope") if isinstance(session_start.get("target_scope"), Mapping) else {}
    schema = tool.get("arguments_schema") if isinstance(tool.get("arguments_schema"), Mapping) else {}
    properties = schema.get("properties") if isinstance(schema.get("properties"), Mapping) else {}
    required = schema.get("required") if isinstance(schema.get("required"), list) else []
    arguments: dict[str, str | int] = {}
    for key in required:
        if key == "namespace":
            value = _string(target_scope.get("namespace"))
        elif key == "service":
            value = _string(target_scope.get("service"))
        elif key == "selector":
            service = _string(target_scope.get("service"))
            value = f"app={service}" if service else "app=unknown"
        elif key == "command":
            value = f"incidentctl inspect {_string(tool.get('tool_id'))}"
        elif key == "timeout_ms":
            arguments[key] = min(_investigation_max_duration_ms(session_start), 5000)
            continue
        else:
            value = _string(target_scope.get(key)) or "fixture"
        if value:
            arguments[key] = value
    for key, property_schema in properties.items():
        if key in arguments or not isinstance(property_schema, Mapping):
            continue
        if key == "timeout_ms":
            arguments[key] = min(_investigation_max_duration_ms(session_start), 5000)
    return arguments


def _evidence_item_from_tool_result(
    tool: Mapping[str, Any],
    tool_result: Mapping[str, Any],
    session_start: Mapping[str, Any],
) -> dict[str, Any]:
    target_scope = session_start.get("target_scope") if isinstance(session_start.get("target_scope"), Mapping) else {}
    evidence_id = _string(tool_result.get("evidence_id")) or _string(tool_result.get("tool_call_id")) or _string(tool.get("tool_id"))
    summary = _string(tool_result.get("redacted_summary")) or _string(tool.get("title")) or "tool returned redacted evidence"
    return {
        "evidence_id": evidence_id,
        "adapter_id": _string(tool_result.get("tool_id")) or _string(tool.get("tool_id")) or "fixture.tool",
        "title": _string(tool.get("title")) or _string(tool.get("tool_id")) or "Investigation evidence",
        "source_kind": _source_kind_from_tool(tool),
        "content_type": "text",
        "content": {
            "format": "text",
            "body": summary,
            "redaction_summary": "redacted by investigation tool contract",
        },
        "time_window": None,
        "source_ref": None,
        "redacted": True,
        "untrusted": False,
        "metadata": {
            "namespace": _string(target_scope.get("namespace")) or None,
            "service": _string(target_scope.get("service")) or None,
            "tool_status": _string(tool_result.get("status")),
        },
    }


def _filter_actions_by_policy(actions: Any, policy: Any) -> list[dict[str, Any]]:
    if not isinstance(policy, Mapping) or policy.get("proposed_actions_allowed") is False:
        return []

    max_action_class = policy.get("max_action_class")
    if not isinstance(max_action_class, int):
        max_action_class = 3

    allowed_classes = policy.get("allowed_action_classes")
    allowed_class_set = (
        {value for value in allowed_classes if isinstance(value, int)} if isinstance(allowed_classes, list) else None
    )

    allowed_ids = policy.get("allowed_action_ids")
    allowed_id_set = {value for value in allowed_ids if isinstance(value, str) and value} if isinstance(allowed_ids, list) else None

    filtered: list[dict[str, Any]] = []
    for action in actions if isinstance(actions, list) else []:
        if not isinstance(action, dict):
            continue
        action_class = action.get("action_class")
        action_id = action.get("action_id")
        if not isinstance(action_class, int) or action_class > max_action_class:
            continue
        if allowed_class_set and action_class not in allowed_class_set:
            continue
        if allowed_id_set and action_id not in allowed_id_set:
            continue
        filtered.append(action)
    return filtered


def _action(
    action_id: str,
    summary: str,
    action_class: int,
    mutation_type: str,
    dry_run_only: bool,
    requires_human_approval: bool,
    evidence_refs: Sequence[str],
    params: Mapping[str, str | int | float | bool | None],
) -> dict[str, Any]:
    return {
        "action_id": action_id,
        "summary": summary,
        "action_class": action_class,
        "mutation_type": mutation_type,
        "dry_run_only": dry_run_only,
        "requires_human_approval": requires_human_approval,
        "evidence_refs": list(evidence_refs),
        "params": dict(params),
    }


def _evidence_ref(evidence_id: str | None, relevance: str, claim: str) -> dict[str, str] | None:
    if not evidence_id:
        return None
    return {"evidence_id": evidence_id, "relevance": relevance, "claim": claim}


def _evidence_items(request: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    items = request.get("evidence_items")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, Mapping)]


def _item_has_missing_database_pool_signal(item: Mapping[str, Any]) -> bool:
    metadata = item.get("metadata")
    missing_adapter = metadata.get("missing_adapter") if isinstance(metadata, Mapping) else ""
    text = _evidence_text(item).lower()
    return (
        "database.pool_status" in str(missing_adapter)
        or "no database pool metric" in text
        or "database pool evidence" in text and "missing" in text
        or "database" in text and "did not return data" in text
    )


def _has_ambiguous_low_signal(evidence: Sequence[Mapping[str, Any]]) -> bool:
    text = "\n".join(_evidence_text(item) for item in evidence).lower()
    return any(marker in text for marker in ("ambiguous", "low-signal", "conflicting", "does not isolate", "no causal"))


def _has_strong_causal_signal(signals: Sequence[SymptomSignal]) -> bool:
    causal = {"connection", "queue_depth", "config_mismatch", "resource_exhaustion"}
    return any(signal.type in causal and signal.severity == "critical" for signal in signals)


def _has_positive_database_pool_signal(item: Mapping[str, Any]) -> bool:
    text = _evidence_text(item).lower()
    adapter = _string(item.get("adapter_id")).lower()
    if any(marker in text for marker in ("no database", "without database", "not database")):
        return False
    return any(
        marker in text
        for marker in (
            "database connection",
            "connection pool",
            "postgres_pool",
            "pool_in_use",
            "pool wait",
            "max_connections",
        )
    )


def _negated_keyword(full_text: str, keyword: str) -> bool:
    return any(
        phrase in full_text
        for phrase in (
            f"no {keyword}",
            f"without {keyword}",
            f"not {keyword}",
            f"no {keyword} error",
            f"no {keyword} metric",
        )
    )


def _evidence_text(item: Mapping[str, Any]) -> str:
    content = item.get("content")
    body = content.get("body") if isinstance(content, Mapping) else None
    parts = [item.get("evidence_id"), item.get("adapter_id"), item.get("title"), body]
    return " ".join(part for part in parts if isinstance(part, str))


def _ids(evidence: Sequence[Mapping[str, Any]]) -> list[str]:
    return [item["evidence_id"] for item in evidence if isinstance(item.get("evidence_id"), str)]


def _first_matching(evidence: Sequence[Mapping[str, Any]], needles: Sequence[str]) -> str | None:
    lowered_needles = [needle.lower() for needle in needles]
    for item in evidence:
        searchable = " ".join(
            str(part)
            for part in (
                item.get("evidence_id"),
                item.get("adapter_id"),
                item.get("title"),
                item.get("source_kind"),
                item.get("content_type"),
            )
            if isinstance(part, str)
        ).lower()
        if any(needle in searchable for needle in lowered_needles):
            return item.get("evidence_id") if isinstance(item.get("evidence_id"), str) else None

    for item in evidence:
        text = _evidence_text(item).lower()
        if any(needle in text for needle in lowered_needles):
            return item.get("evidence_id") if isinstance(item.get("evidence_id"), str) else None
    return None


def _first_by_adapter(evidence: Sequence[Mapping[str, Any]], prefixes: Sequence[str]) -> str | None:
    for item in evidence:
        adapter = item.get("adapter_id")
        evidence_id = item.get("evidence_id")
        adapter_text = adapter.lower() if isinstance(adapter, str) else ""
        evidence_text = evidence_id.lower() if isinstance(evidence_id, str) else ""
        if any(adapter_text.startswith(f"{prefix}.") or evidence_text.startswith(f"{prefix}.") for prefix in prefixes):
            return evidence_id if isinstance(evidence_id, str) else None
    return None


def _compact(values: Sequence[str | None]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _compact_dicts(values: Sequence[dict[str, Any] | None]) -> list[dict[str, Any]]:
    return [value for value in values if value is not None]


def _unique_strings(values: Sequence[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _at(values: Sequence[str], index: int) -> str | None:
    return values[index] if len(values) > index else None


def _route_confidence(route: Mapping[str, Any] | None, default: float) -> float:
    if route is None:
        return default
    value = route.get("confidence")
    return float(value) if isinstance(value, (int, float)) else default


def _severity_weight(severity: str) -> float:
    return {"critical": 1.0, "warning": 0.6, "info": 0.3}.get(severity, 0.3)


def _infer_severity(text: str) -> str:
    lowered = text.lower()
    if any(marker in lowered for marker in ("100 percent", "critical", "crashloop", "exceeded", "rose from", "oomkilled")):
        return "critical"
    if any(marker in lowered for marker in ("warning", "increased", "timeout", "5xx", "503", "mismatch")):
        return "warning"
    return "info"


def _safe_name(value: str) -> str:
    chars: list[str] = []
    last_dash = False
    for char in value.lower():
        if char.isalnum():
            chars.append(char)
            last_dash = False
        elif not last_dash:
            chars.append("-")
            last_dash = True
    return "".join(chars).strip("-") or "case"


def _string_value(value: Any, *, default: str = "") -> str:
    return value if isinstance(value, str) else default


def _string(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _source_kind_from_tool(tool: Mapping[str, Any]) -> str:
    provider = _string(tool.get("provider"))
    if provider in {"service", "kubernetes", "queue", "database", "config"}:
        return {"service": "log", "kubernetes": "event", "queue": "metric", "database": "metric", "config": "event"}[provider]
    return "fixture"


def _skill_domains_from_session(session_start: Mapping[str, Any]) -> list[str]:
    providers = [
        _string(tool.get("provider"))
        for tool in session_start.get("tool_catalog", [])
        if isinstance(tool, Mapping) and _string(tool.get("provider")) != "sandbox"
    ]
    return _unique_strings([provider for provider in providers if provider]) or ["service"]


def _investigation_max_steps(session_start: Mapping[str, Any]) -> int:
    policy = session_start.get("investigation_policy") if isinstance(session_start.get("investigation_policy"), Mapping) else {}
    return policy.get("max_steps") if isinstance(policy.get("max_steps"), int) else 1


def _investigation_max_duration_ms(session_start: Mapping[str, Any]) -> int:
    policy = session_start.get("investigation_policy") if isinstance(session_start.get("investigation_policy"), Mapping) else {}
    return policy.get("max_duration_ms") if isinstance(policy.get("max_duration_ms"), int) else 1


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
