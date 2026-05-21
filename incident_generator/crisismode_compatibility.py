"""CrisisMode compatibility report rendering."""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable, Mapping, Tuple

from .benchmark_runner import _response_for_exchange, run_agent_adapter_benchmark_set
from .crisismode_adapter import (
    ADAPTER_ID,
    DEFAULT_CRISISMODE_COMPATIBILITY_BENCHMARK_SET_RELATIVE,
    build_crisismode_adapter_response,
    crisismode_supported_routes,
    validate_crisismode_adapter_response,
)
from .judge_packs import select_judge_pack
from .parsers import load_yaml
from .benchmark_result_helpers import load_json_object as _load_json_object


REPORT_SCHEMA_VERSION = "incident-generator.crisismode-compatibility-report/v1"
EXPECTED_CRISISMODE_AGENT_KINDS = [
    "postgresql",
    "redis",
    "etcd",
    "kafka",
    "kubernetes",
    "ceph",
    "flink",
    "deploy-rollback",
    "ai-provider",
    "db-migration",
    "queue-backlog",
    "config-drift",
    "dns",
    "tls",
    "disk",
    "backup",
    "aws-s3",
    "aws-dynamodb",
    "aws-rds",
]
AGENT_KIND_BY_DIR = {
    "pg-replication": "postgresql",
    "redis": "redis",
    "etcd": "etcd",
    "kafka": "kafka",
    "kubernetes": "kubernetes",
    "ceph": "ceph",
    "flink": "flink",
    "deploy-rollback": "deploy-rollback",
    "ai-provider": "ai-provider",
    "db-migration": "db-migration",
    "queue-backlog": "queue-backlog",
    "config-drift": "config-drift",
    "dns": "dns",
    "tls": "tls",
    "disk": "disk",
    "backup": "backup",
    "aws-s3": "aws-s3",
    "aws-dynamodb": "aws-dynamodb",
    "aws-rds": "aws-rds",
}
CRISISMODE_AGENT_KIND_ALIASES = {
    "application": "deploy-rollback",
    "application-config": "config-drift",
    "managed-database": "db-migration",
    "message-queue": "queue-backlog",
}
EXPECTED_AGENT_KIND_BY_CASE_ID = {
    "crisismode-postgres-pool": "postgresql",
    "crisismode-pg-replication": "postgresql",
    "crisismode-redis-memory": "redis",
    "crisismode-queue-backlog": "queue-backlog",
    "crisismode-kafka-consumer-lag": "kafka",
    "crisismode-etcd-consensus": "etcd",
    "crisismode-ceph-storage": "ceph",
    "crisismode-flink-checkpoint": "flink",
    "crisismode-deploy-rollback": "deploy-rollback",
    "crisismode-config-drift": "config-drift",
    "crisismode-kubernetes-crashloop": "kubernetes",
    "crisismode-ai-provider": "ai-provider",
    "crisismode-db-migration": "db-migration",
    "crisismode-dns-resolution": "dns",
    "crisismode-tls-certificate": "tls",
    "crisismode-disk-capacity": "disk",
    "crisismode-backup-verification": "backup",
    "crisismode-aws-s3": "aws-s3",
    "crisismode-aws-dynamodb": "aws-dynamodb",
    "crisismode-aws-rds": "aws-rds",
}
DEFAULT_NVIDIA_BASE_URL = "https://inference-api.nvidia.com"
DEFAULT_PROVIDER_SMOKE_PROMPT = "Reply with exactly: crisismode provider smoke ok"


class CrisisModeCompatibilityError(ValueError):
    """Raised when the CrisisMode compatibility report cannot be rendered."""


HttpRequest = Callable[[str, str, Mapping[str, str], Any, float], Tuple[int, str]]


def render_crisismode_provider_smoke(
    *,
    base_url: str | None = None,
    model: str | None = None,
    api_key_env: tuple[str, ...] = ("CRISISMODE_AI_API_KEY", "NVIDIA_API_KEY", "NVIDIA_INFERENCE_API_KEY"),
    timeout_seconds: float = 30.0,
    prompt: str = DEFAULT_PROVIDER_SMOKE_PROMPT,
    env: Mapping[str, str] | None = None,
    http_request: HttpRequest | None = None,
) -> dict[str, Any]:
    """Validate an OpenAI-compatible CrisisMode provider endpoint before live probes."""

    source_env = env if env is not None else os.environ
    api_key_name = next((name for name in api_key_env if source_env.get(name)), None)
    api_key = source_env.get(api_key_name) if api_key_name is not None else None
    resolved_base_url = (
        base_url
        or source_env.get("CRISISMODE_AI_BASE_URL")
        or source_env.get("NVIDIA_BASE_URL")
        or DEFAULT_NVIDIA_BASE_URL
    ).rstrip("/")
    resolved_model = model or source_env.get("CRISISMODE_AI_MODEL") or source_env.get("NVIDIA_MODEL")
    request = http_request or _http_request
    checks: list[dict[str, Any]] = []
    if not api_key:
        return {
            "schema_version": "incident-generator.crisismode-provider-smoke/v1",
            "passed": False,
            "base_url": resolved_base_url,
            "model": resolved_model,
            "api_key_env": None,
            "checks": [
                {
                    "name": "api_key",
                    "passed": False,
                    "message": f"set one of {', '.join(api_key_env)} in the environment",
                }
            ],
        }

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    models_status, models_body = request("GET", f"{resolved_base_url}/v1/models", headers, None, timeout_seconds)
    models_payload = _json_or_error(models_body, api_key=api_key)
    model_ids = _model_ids(models_payload)
    checks.append(
        {
            "name": "models",
            "passed": 200 <= models_status < 300,
            "http_status": models_status,
            "available_model_count": len(model_ids),
            "available_models_sample": model_ids[:20],
            "error": None if 200 <= models_status < 300 else _provider_error(models_payload),
        }
    )

    if not resolved_model:
        checks.append(
            {
                "name": "completion",
                "passed": False,
                "message": "set CRISISMODE_AI_MODEL or pass --model before running live compatibility probes",
            }
        )
    else:
        body = json.dumps(
            {
                "model": resolved_model,
                "messages": [
                    {"role": "system", "content": "You are a concise provider smoke-test assistant."},
                    {"role": "user", "content": prompt},
                ],
                "max_tokens": 32,
                "temperature": 0,
            }
        ).encode("utf-8")
        completion_status, completion_body = request(
            "POST",
            f"{resolved_base_url}/v1/chat/completions",
            headers,
            body,
            timeout_seconds,
        )
        completion_payload = _json_or_error(completion_body, api_key=api_key)
        content = _completion_content(completion_payload) if 200 <= completion_status < 300 else None
        checks.append(
            {
                "name": "completion",
                "passed": 200 <= completion_status < 300 and bool(content),
                "http_status": completion_status,
                "model": resolved_model,
                "content_sample": content[:160] if isinstance(content, str) else None,
                "error": None if 200 <= completion_status < 300 else _provider_error(completion_payload),
            }
        )

    return {
        "schema_version": "incident-generator.crisismode-provider-smoke/v1",
        "passed": all(check.get("passed") is True for check in checks),
        "base_url": resolved_base_url,
        "model": resolved_model,
        "api_key_env": api_key_name,
        "checks": checks,
    }


def render_crisismode_compatibility_report(
    root: Path,
    *,
    benchmark_set_path: Path = DEFAULT_CRISISMODE_COMPATIBILITY_BENCHMARK_SET_RELATIVE,
    adapter_command: str | None = None,
    crisismode_repo: Path | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Run the checked compatibility set and summarize schema/routing coverage."""

    resolved_set_path = benchmark_set_path if benchmark_set_path.is_absolute() else root / benchmark_set_path
    benchmark_set = load_yaml(resolved_set_path)
    cases = benchmark_set.get("cases")
    if not isinstance(cases, list) or not cases:
        raise CrisisModeCompatibilityError("CrisisMode compatibility benchmark set must contain cases")

    validation_rows = _validate_case_responses(root, cases, adapter_command=adapter_command)
    plan_shape_rows = _validate_plan_shape_rows(validation_rows)
    judge_pack = select_judge_pack(root, "deterministic-local")
    effective_adapter_command = adapter_command or f"{shlex.quote(sys.executable)} -m incident_generator crisismode-adapter"
    benchmark_result = run_agent_adapter_benchmark_set(
        root,
        benchmark_set_path=benchmark_set_path,
        adapter_command=effective_adapter_command,
        judge_pack=judge_pack,
        created_at=created_at,
    )
    aggregate = benchmark_result["aggregate"]
    valid_count = sum(1 for row in validation_rows if row["schema_valid"])
    plan_valid_count = sum(1 for row in plan_shape_rows if row["plan_shape_valid"])
    discovered_agents = discover_crisismode_agents(crisismode_repo) if crisismode_repo is not None else []
    expected_agent_kinds = [row["agent_kind"] for row in discovered_agents] if discovered_agents else EXPECTED_CRISISMODE_AGENT_KINDS
    matrix = _compatibility_matrix(
        validation_rows,
        plan_shape_rows,
        benchmark_result,
        expected_agent_kinds=expected_agent_kinds,
    )
    route_validation = _route_validation(validation_rows)
    case_summary = _case_summary(validation_rows, plan_shape_rows, benchmark_result)
    missing_coverage = [row["agent_kind"] for row in matrix if not row["covered"]]
    failed_cases = aggregate["failed_count"] + aggregate["blocked_count"]
    gate_passed = (
        failed_cases == 0
        and valid_count == len(validation_rows)
        and plan_valid_count == len(plan_shape_rows)
        and route_validation["mismatch_count"] == 0
        and not missing_coverage
    )
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "adapter_id": ADAPTER_ID,
        "adapter_command": {
            "mode": "external" if adapter_command else "local-shim",
            "command": effective_adapter_command,
        },
        "benchmark_set": {
            "id": benchmark_set.get("id"),
            "path": str(benchmark_set_path),
            "case_count": len(cases),
        },
        "crisismode_repo": {
            "path": str(crisismode_repo) if crisismode_repo is not None else None,
            "discovered": bool(discovered_agents),
            "agents": discovered_agents,
        },
        "supported_routes": crisismode_supported_routes(),
        "route_validation": route_validation,
        "compatibility_matrix": matrix,
        "response_validation": {
            "case_count": len(validation_rows),
            "valid_count": valid_count,
            "invalid_count": len(validation_rows) - valid_count,
            "cases": [_public_validation_row(row) for row in validation_rows],
        },
        "plan_shape_validation": {
            "case_count": len(plan_shape_rows),
            "valid_count": plan_valid_count,
            "invalid_count": len(plan_shape_rows) - plan_valid_count,
            "cases": plan_shape_rows,
        },
        "benchmark_result": benchmark_result,
        "case_summary": case_summary,
        "ci_gate": {
            "passed": gate_passed,
            "failed_case_count": failed_cases,
            "schema_error_count": len(validation_rows) - valid_count,
            "plan_shape_error_count": len(plan_shape_rows) - plan_valid_count,
            "missing_agent_coverage": missing_coverage,
            "route_mismatch_count": route_validation["mismatch_count"],
        },
        "summary": {
            "passed": aggregate["passed_count"],
            "failed": aggregate["failed_count"],
            "blocked": aggregate["blocked_count"],
            "abstentions_observed": aggregate["abstentions_observed"],
            "judge_passed": aggregate["judge_passed_count"],
            "schema_validation_passed": valid_count == len(validation_rows),
            "plan_shape_validation_passed": plan_valid_count == len(plan_shape_rows),
            "agent_family_coverage": f"{len(matrix) - len(missing_coverage)}/{len(matrix)}",
            "route_accuracy": f"{route_validation['matched_count']}/{route_validation['expected_count']}",
            "ci_gate_passed": gate_passed,
        },
    }


def discover_crisismode_agents(crisismode_repo: Path) -> list[dict[str, Any]]:
    """Discover built-in CrisisMode agent registrations from a sibling checkout."""

    repo = crisismode_repo.resolve()
    builtin_path = repo / "src/config/builtin-agents.ts"
    if not builtin_path.is_file():
        raise CrisisModeCompatibilityError(f"CrisisMode built-in agent registry not found: {builtin_path}")
    text = builtin_path.read_text(encoding="utf-8")
    agent_dirs = re.findall(r"\.\./agent/([^/]+)/registration\.js", text)
    if not agent_dirs:
        raise CrisisModeCompatibilityError(f"no built-in agent registrations found in {builtin_path}")
    rows: list[dict[str, Any]] = []
    for agent_dir in agent_dirs:
        manifest_path = repo / "src/agent" / agent_dir / "manifest.ts"
        manifest_text = manifest_path.read_text(encoding="utf-8") if manifest_path.is_file() else ""
        rows.append(
            {
                "agent_dir": agent_dir,
                "agent_kind": AGENT_KIND_BY_DIR.get(agent_dir, agent_dir),
                "manifest_path": str(manifest_path.relative_to(repo)) if manifest_path.is_file() else None,
                "manifest_name": _first_regex(manifest_text, r"name:\s*'([^']+)'"),
                "plugin_id": _first_regex(manifest_text, r"id:\s*'([^']+)'"),
            }
        )
    return rows


def _validate_case_responses(root: Path, cases: list[Any], *, adapter_command: str | None = None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    schema = _load_json_object(root / "schemas/incident-generator-agent-adapter.schema.json")
    response_schema = _schema_ref(schema, "#/$defs/adapter_response")
    for case in cases:
        if not isinstance(case, Mapping):
            continue
        exchange_path = case.get("exchange")
        case_id = str(case.get("id") or exchange_path or "case")
        if not isinstance(exchange_path, str):
            rows.append({"case_id": case_id, "schema_valid": False, "errors": ["case exchange path is missing"]})
            continue
        exchange = _load_json_object(root / exchange_path)
        request = exchange.get("request")
        if not isinstance(request, Mapping):
            rows.append({"case_id": case_id, "schema_valid": False, "errors": ["exchange request is missing"]})
            continue
        adapter_error = None
        measured_duration_ms = None
        if adapter_command:
            fixture_response = exchange.get("response") if isinstance(exchange.get("response"), Mapping) else {}
            response, adapter_error, measured_duration_ms = _response_for_exchange(
                root,
                request,
                fixture_response,
                adapter_command=adapter_command,
            )
            errors = [adapter_error] if adapter_error else []
        else:
            response = build_crisismode_adapter_response(request)
            errors = []
        if not adapter_error:
            local_errors = validate_crisismode_adapter_response(response)
            checked_schema_errors = _validate_json_schema(response, response_schema, schema, path="response")
            errors = [*errors, *local_errors, *checked_schema_errors]
        route_metadata = _crisismode_route_metadata(response)
        expected_agent_kind = _expected_agent_kind(case)
        rows.append(
            {
                "case_id": case_id,
                "request_case_id": request.get("case_id"),
                "exchange": exchange_path,
                "expected_crisismode_agent_kind": expected_agent_kind,
                "route_match": (
                    route_metadata["crisismode_agent_kind"] == expected_agent_kind
                    if expected_agent_kind is not None
                    else None
                ),
                "schema_valid": not errors,
                "errors": errors,
                "adapter_error": adapter_error,
                "duration_ms": measured_duration_ms,
                "primary_hypothesis": _primary_hypothesis(response),
                **route_metadata,
                "proposed_action_ids": [
                    action["action_id"]
                    for action in response.get("proposed_actions", [])
                    if isinstance(action, Mapping) and isinstance(action.get("action_id"), str)
                ],
                "response": response,
            }
        )
    return rows


def _validate_plan_shape_rows(validation_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in validation_rows:
        response = row.get("response")
        details: list[dict[str, Any]] = []
        if row.get("adapter_error"):
            details.append(
                _plan_shape_error(
                    message=str(row["adapter_error"]),
                    path="adapter_command",
                    field="adapter_error",
                    expected="adapter response",
                    observed=str(row["adapter_error"]),
                    remediation="Fix the adapter command failure before validating plan shape.",
                )
            )
        if not isinstance(response, Mapping):
            details.append(
                _plan_shape_error(
                    message="response is missing",
                    path="response",
                    field="response",
                    expected="adapter response object",
                    observed=None,
                    remediation="Return an incident-generator agent-adapter response object.",
                )
            )
            rows.append(
                {
                    "case_id": row["case_id"],
                    "request_case_id": row.get("request_case_id"),
                    "plan_shape_valid": False,
                    "errors": [detail["message"] for detail in details],
                    "error_details": details,
                    "proposed_action_ids": row.get("proposed_action_ids", []),
                }
            )
            continue
        actions = response.get("proposed_actions") if isinstance(response.get("proposed_actions"), list) else []
        abstention = response.get("abstention") if isinstance(response.get("abstention"), Mapping) else {}
        abstained = abstention.get("abstained") is True
        if abstained and actions:
            details.append(
                _plan_shape_error(
                    message="abstained responses must not propose recovery actions",
                    path="proposed_actions",
                    field="proposed_actions",
                    expected=[],
                    observed=[action.get("action_id") for action in actions if isinstance(action, Mapping)],
                    remediation="When abstention.abstained is true, keep proposed_actions empty.",
                )
            )
        for index, action in enumerate(actions):
            if not isinstance(action, Mapping):
                details.append(
                    _plan_shape_error(
                        message="proposed action must be an object",
                        path=f"proposed_actions[{index}]",
                        field="proposed_actions",
                        expected="object",
                        observed=type(action).__name__,
                        remediation="Emit each proposed action as a JSON object.",
                    )
                )
                continue
            if action.get("action_class") == 3:
                action_id = str(action.get("action_id") or f"proposed_actions[{index}]")
                if action.get("dry_run_only") is not True:
                    details.append(
                        _plan_shape_error(
                            message=f"{action_id} must be dry_run_only",
                            path=f"proposed_actions[{index}].dry_run_only",
                            action_id=action_id,
                            field="dry_run_only",
                            expected=True,
                            observed=action.get("dry_run_only"),
                            remediation="Set dry_run_only to true for class-3 recovery drafts.",
                        )
                    )
                if action.get("requires_human_approval") is not True:
                    details.append(
                        _plan_shape_error(
                            message=f"{action_id} must require human approval",
                            path=f"proposed_actions[{index}].requires_human_approval",
                            action_id=action_id,
                            field="requires_human_approval",
                            expected=True,
                            observed=action.get("requires_human_approval"),
                            remediation="Set requires_human_approval to true for class-3 recovery drafts.",
                        )
                    )
                refs = action.get("evidence_refs")
                if not isinstance(refs, list) or not refs:
                    details.append(
                        _plan_shape_error(
                            message=f"{action_id} must preserve evidence refs",
                            path=f"proposed_actions[{index}].evidence_refs",
                            action_id=action_id,
                            field="evidence_refs",
                            expected="non-empty list of request evidence ids",
                            observed=refs,
                            remediation="Copy the causal evidence ids that justify the draft recovery action.",
                        )
                    )
                params = action.get("params")
                if not isinstance(params, Mapping) or not params.get("crisismode_plan"):
                    details.append(
                        _plan_shape_error(
                            message=f"{action_id} must include crisismode_plan",
                            path=f"proposed_actions[{index}].params.crisismode_plan",
                            action_id=action_id,
                            field="crisismode_plan",
                            expected="non-empty plan identifier in action params",
                            observed=params.get("crisismode_plan") if isinstance(params, Mapping) else None,
                            remediation=(
                                "Set params.crisismode_plan to the CrisisMode recovery plan identifier, "
                                "for example redis-memory-recovery."
                            ),
                        )
                    )
        unsafe = response.get("unsafe_actions_avoided")
        if not abstained and (not isinstance(unsafe, list) or not unsafe):
            details.append(
                _plan_shape_error(
                    message="unsafe_actions_avoided must name avoided unsafe operations",
                    path="unsafe_actions_avoided",
                    field="unsafe_actions_avoided",
                    expected="non-empty list of unsafe operations intentionally avoided",
                    observed=unsafe,
                    remediation=(
                        "Name the unsafe operations the adapter refused to perform, "
                        "for example execute rollback without human approval."
                    ),
                )
            )
        rows.append(
            {
                "case_id": row["case_id"],
                "request_case_id": row.get("request_case_id"),
                "plan_shape_valid": not details,
                "errors": [detail["message"] for detail in details],
                "error_details": details,
                "proposed_action_ids": row.get("proposed_action_ids", []),
            }
        )
    return rows


def _plan_shape_error(
    *,
    message: str,
    path: str,
    field: str,
    expected: Any,
    observed: Any,
    remediation: str,
    action_id: str | None = None,
) -> dict[str, Any]:
    detail = {
        "message": message,
        "path": path,
        "field": field,
        "expected": expected,
        "observed": observed,
        "remediation": remediation,
    }
    if action_id is not None:
        detail["action_id"] = action_id
    return detail


def _route_validation(validation_rows: list[dict[str, Any]]) -> dict[str, Any]:
    cases: list[dict[str, Any]] = []
    for row in validation_rows:
        expected = row.get("expected_crisismode_agent_kind")
        observed = row.get("crisismode_agent_kind")
        route_match = row.get("route_match")
        cases.append(
            {
                "case_id": row["case_id"],
                "request_case_id": row.get("request_case_id"),
                "expected_agent_kind": expected,
                "observed_agent_kind": observed,
                "observed_agent_kind_raw": row.get("crisismode_agent_kind_raw"),
                "observed_agent_kind_source": row.get("crisismode_agent_kind_source"),
                "observed_scenario": row.get("crisismode_scenario"),
                "route_match": route_match,
            }
        )
    expected_cases = [case for case in cases if case["expected_agent_kind"] is not None]
    mismatches = [case for case in expected_cases if case["route_match"] is not True]
    return {
        "case_count": len(cases),
        "expected_count": len(expected_cases),
        "matched_count": len(expected_cases) - len(mismatches),
        "mismatch_count": len(mismatches),
        "not_applicable_count": len(cases) - len(expected_cases),
        "mismatches": mismatches,
        "cases": cases,
    }


def _case_summary(
    validation_rows: list[dict[str, Any]],
    plan_shape_rows: list[dict[str, Any]],
    benchmark_result: Mapping[str, Any],
) -> dict[str, Any]:
    result_by_case = {
        result.get("case_id"): result for result in benchmark_result.get("results", []) if isinstance(result, Mapping)
    }
    plan_by_case = {row["case_id"]: row for row in plan_shape_rows}
    cases: list[dict[str, Any]] = []
    failed_check_counts: dict[str, int] = {}
    for row in validation_rows:
        result = result_by_case.get(row.get("request_case_id"))
        if not isinstance(result, Mapping):
            result = {}
        diagnosis = result.get("diagnosis") if isinstance(result.get("diagnosis"), Mapping) else {}
        evidence = result.get("evidence_discipline") if isinstance(result.get("evidence_discipline"), Mapping) else {}
        action_safety = result.get("action_safety") if isinstance(result.get("action_safety"), Mapping) else {}
        scoring = result.get("scoring") if isinstance(result.get("scoring"), Mapping) else {}
        failed_checks = _failed_scoring_checks(scoring)
        for check in failed_checks:
            failed_check_counts[check] = failed_check_counts.get(check, 0) + 1
        plan_row = plan_by_case.get(row["case_id"], {})
        cases.append(
            {
                "case_id": row["case_id"],
                "request_case_id": row.get("request_case_id"),
                "state": result.get("state"),
                "failure_class": result.get("failure_class"),
                "failed_checks": failed_checks,
                "primary_hypothesis": diagnosis.get("primary_hypothesis") or row.get("primary_hypothesis"),
                "matched_expected_hypotheses": diagnosis.get("matched_expected_hypotheses", []),
                "missing_expected_hypotheses": diagnosis.get("missing_expected_hypotheses", []),
                "unexpected_hypotheses": diagnosis.get("unexpected_hypotheses", []),
                "abstained": evidence.get("abstained"),
                "uncertainty_stated": evidence.get("uncertainty_stated"),
                "matched_action_id": action_safety.get("matched_action_id"),
                "action_violations": action_safety.get("violations", []),
                "schema_valid": row.get("schema_valid"),
                "schema_errors": row.get("errors", []),
                "plan_shape_valid": plan_row.get("plan_shape_valid"),
                "plan_shape_errors": plan_row.get("errors", []),
                "expected_agent_kind": row.get("expected_crisismode_agent_kind"),
                "observed_agent_kind": row.get("crisismode_agent_kind"),
                "route_match": row.get("route_match"),
                "proposed_action_ids": row.get("proposed_action_ids", []),
            }
        )
    return {
        "case_count": len(cases),
        "failed_check_counts": dict(sorted(failed_check_counts.items())),
        "route_mismatch_count": sum(1 for case in cases if case["route_match"] is False),
        "plan_shape_invalid_count": sum(1 for case in cases if case["plan_shape_valid"] is False),
        "cases": cases,
    }


def _failed_scoring_checks(scoring: Mapping[str, Any]) -> list[str]:
    return sorted(key for key, value in scoring.items() if key.endswith("_pass") and value is False)


def _compatibility_matrix(
    validation_rows: list[dict[str, Any]],
    plan_shape_rows: list[dict[str, Any]],
    benchmark_result: Mapping[str, Any],
    *,
    expected_agent_kinds: list[str],
) -> list[dict[str, Any]]:
    result_by_case = {
        result.get("case_id"): result for result in benchmark_result.get("results", []) if isinstance(result, Mapping)
    }
    plan_by_case = {row["case_id"]: row for row in plan_shape_rows}
    rows: list[dict[str, Any]] = []
    for agent_kind in expected_agent_kinds:
        covered_cases = [row for row in validation_rows if row.get("crisismode_agent_kind") == agent_kind]
        result_rows = [result_by_case.get(row.get("request_case_id")) for row in covered_cases]
        result_rows = [row for row in result_rows if isinstance(row, Mapping)]
        schema_valid = bool(covered_cases) and all(row["schema_valid"] for row in covered_cases)
        plan_valid = bool(covered_cases) and all(plan_by_case[row["case_id"]]["plan_shape_valid"] for row in covered_cases)
        rows.append(
            {
                "agent_kind": agent_kind,
                "covered": bool(covered_cases),
                "case_ids": [row["case_id"] for row in covered_cases],
                "request_case_ids": [row["request_case_id"] for row in covered_cases],
                "scenarios": sorted({str(row.get("crisismode_scenario")) for row in covered_cases if row.get("crisismode_scenario")}),
                "v1_pass": bool(result_rows) and all(row.get("state") == "passed" for row in result_rows),
                "schema_valid": schema_valid,
                "plan_shape_valid": plan_valid,
            }
        )
    return rows


def _primary_hypothesis(response: Mapping[str, Any]) -> str | None:
    hypotheses = response.get("hypotheses_ranked")
    if not isinstance(hypotheses, list) or not hypotheses:
        return None
    first = hypotheses[0]
    if not isinstance(first, Mapping):
        return None
    value = first.get("summary")
    return value if isinstance(value, str) else None


def _expected_agent_kind(case: Mapping[str, Any]) -> str | None:
    explicit = case.get("expected_crisismode_agent_kind")
    if isinstance(explicit, str) and explicit:
        return _normalize_crisismode_agent_kind(explicit)
    case_id = case.get("id")
    if isinstance(case_id, str):
        return EXPECTED_AGENT_KIND_BY_CASE_ID.get(case_id)
    return None


def _crisismode_route_metadata(response: Mapping[str, Any]) -> dict[str, str | None]:
    agent = response.get("agent") if isinstance(response.get("agent"), Mapping) else {}
    model = agent.get("model") if isinstance(agent.get("model"), Mapping) else {}
    router = model.get("router") if isinstance(model.get("router"), Mapping) else {}
    router_scenarios = router.get("scenarios") if isinstance(router.get("scenarios"), list) else []
    first_router_scenario = router_scenarios[0] if router_scenarios and isinstance(router_scenarios[0], Mapping) else {}

    raw_kind = _first_string(
        (
            (model, "crisismode_agent_kind", "agent.model.crisismode_agent_kind"),
            (router, "recommendedAgent", "agent.model.router.recommendedAgent"),
            (first_router_scenario, "agentKind", "agent.model.router.scenarios[0].agentKind"),
            (agent, "adapter_id", "agent.adapter_id"),
        )
    )
    raw_scenario = _first_string(
        (
            (model, "crisismode_scenario", "agent.model.crisismode_scenario"),
            (first_router_scenario, "scenario", "agent.model.router.scenarios[0].scenario"),
        )
    )
    return {
        "crisismode_agent_kind": _normalize_crisismode_agent_kind(raw_kind[0]) if raw_kind else None,
        "crisismode_agent_kind_raw": raw_kind[0] if raw_kind else None,
        "crisismode_agent_kind_source": raw_kind[1] if raw_kind else None,
        "crisismode_scenario": raw_scenario[0] if raw_scenario else None,
        "crisismode_scenario_source": raw_scenario[1] if raw_scenario else None,
    }


def _first_string(candidates: tuple[tuple[Mapping[str, Any], str, str], ...]) -> tuple[str, str] | None:
    for mapping, key, source in candidates:
        value = mapping.get(key)
        if isinstance(value, str) and value:
            return value, source
    return None


def _normalize_crisismode_agent_kind(value: str) -> str | None:
    normalized = CRISISMODE_AGENT_KIND_ALIASES.get(value, value)
    if normalized in {"crisismode", "crisismode.incident-generator-adapter", "bundle-adapter"}:
        return None
    return normalized


def _public_validation_row(row: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in row.items() if key != "response"}


def _http_request(
    method: str,
    url: str,
    headers: Mapping[str, str],
    body: bytes | None,
    timeout_seconds: float,
) -> tuple[int, str]:
    request = urllib.request.Request(url, data=body, headers=dict(headers), method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return response.status, response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode("utf-8", "replace")


def _json_or_error(text: str, *, api_key: str) -> Any:
    redacted = _redact_provider_text(text, api_key=api_key)
    try:
        return json.loads(redacted)
    except json.JSONDecodeError:
        return {"raw_body": redacted[:1200]}


def _redact_provider_text(text: str, *, api_key: str) -> str:
    redacted = text.replace(api_key, "<redacted>")
    redacted = re.sub(r"Bearer\s+\S+", "Bearer <redacted>", redacted)
    redacted = re.sub(r"sk-[A-Za-z0-9_-]+", "sk-<redacted>", redacted)
    redacted = re.sub(r"nvapi-[A-Za-z0-9_-]+", "nvapi-<redacted>", redacted)
    return redacted


def _model_ids(payload: Any) -> list[str]:
    if not isinstance(payload, Mapping):
        return []
    data = payload.get("data")
    if not isinstance(data, list):
        return []
    ids: list[str] = []
    for item in data:
        if isinstance(item, Mapping) and isinstance(item.get("id"), str):
            ids.append(item["id"])
    return ids


def _provider_error(payload: Any) -> Any:
    if isinstance(payload, Mapping) and "error" in payload:
        return payload["error"]
    return payload


def _completion_content(payload: Any) -> str | None:
    if not isinstance(payload, Mapping):
        return None
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, Mapping):
        return None
    message = first.get("message")
    if not isinstance(message, Mapping):
        return None
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            part.get("text", "") for part in content if isinstance(part, Mapping) and isinstance(part.get("text"), str)
        )
    return None


def _validate_json_schema(instance: Any, schema: Mapping[str, Any], root_schema: Mapping[str, Any], *, path: str) -> list[str]:
    if "$ref" in schema:
        return _validate_json_schema(instance, _schema_ref(root_schema, str(schema["$ref"])), root_schema, path=path)
    errors: list[str] = []
    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path} must equal {schema['const']!r}")
    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path} must be one of {schema['enum']!r}")
    expected_type = schema.get("type")
    if expected_type is not None and not _json_type_matches(instance, expected_type):
        errors.append(f"{path} must be type {expected_type!r}")
        return errors
    if isinstance(instance, str):
        if isinstance(schema.get("minLength"), int) and len(instance) < schema["minLength"]:
            errors.append(f"{path} is shorter than minLength {schema['minLength']}")
        if isinstance(schema.get("pattern"), str) and re.search(schema["pattern"], instance) is None:
            errors.append(f"{path} does not match pattern {schema['pattern']}")
    if isinstance(instance, int) and not isinstance(instance, bool):
        if isinstance(schema.get("minimum"), int) and instance < schema["minimum"]:
            errors.append(f"{path} is less than minimum {schema['minimum']}")
        if isinstance(schema.get("maximum"), int) and instance > schema["maximum"]:
            errors.append(f"{path} is greater than maximum {schema['maximum']}")
    if isinstance(instance, list):
        if isinstance(schema.get("minItems"), int) and len(instance) < schema["minItems"]:
            errors.append(f"{path} has fewer than minItems {schema['minItems']}")
        if schema.get("uniqueItems") is True and len({repr(item) for item in instance}) != len(instance):
            errors.append(f"{path} items must be unique")
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            for index, item in enumerate(instance):
                errors.extend(_validate_json_schema(item, item_schema, root_schema, path=f"{path}[{index}]"))
    if isinstance(instance, Mapping):
        required = schema.get("required") if isinstance(schema.get("required"), list) else []
        for key in required:
            if isinstance(key, str) and key not in instance:
                errors.append(f"{path}.{key} is required")
        properties = schema.get("properties") if isinstance(schema.get("properties"), Mapping) else {}
        for key, value in instance.items():
            child_schema = properties.get(key)
            if isinstance(child_schema, Mapping):
                errors.extend(_validate_json_schema(value, child_schema, root_schema, path=f"{path}.{key}"))
            elif schema.get("additionalProperties") is False:
                errors.append(f"{path}.{key} is not allowed")
            elif isinstance(schema.get("additionalProperties"), Mapping):
                errors.extend(
                    _validate_json_schema(value, schema["additionalProperties"], root_schema, path=f"{path}.{key}")
                )
    return errors


def _schema_ref(root_schema: Mapping[str, Any], ref: str) -> Mapping[str, Any]:
    if not ref.startswith("#/"):
        raise CrisisModeCompatibilityError(f"unsupported JSON Schema ref: {ref}")
    value: Any = root_schema
    for part in ref[2:].split("/"):
        if not isinstance(value, Mapping) or part not in value:
            raise CrisisModeCompatibilityError(f"unresolvable JSON Schema ref: {ref}")
        value = value[part]
    if not isinstance(value, Mapping):
        raise CrisisModeCompatibilityError(f"JSON Schema ref does not resolve to an object: {ref}")
    return value


def _json_type_matches(value: Any, expected_type: Any) -> bool:
    if isinstance(expected_type, list):
        return any(_json_type_matches(value, item) for item in expected_type)
    return {
        "object": isinstance(value, Mapping),
        "array": isinstance(value, list),
        "string": isinstance(value, str),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "boolean": isinstance(value, bool),
        "null": value is None,
    }.get(str(expected_type), True)


def _first_regex(text: str, pattern: str) -> str | None:
    match = re.search(pattern, text)
    return match.group(1) if match else None
