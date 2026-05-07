"""Markdown comparison views for benchmark-result payloads."""

from __future__ import annotations

import math
import os
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from .benchmark_result_helpers import (
    load_json_object as _load_json_object,
    relative_path as _relative_path,
    resolve_path as _resolve_path,
    sha256_text as _sha256_text,
)
from .benchmark_runner import run_agent_adapter_benchmark_set
from .deterministic_replay_results import render_deterministic_replay_result
from .judge_packs import select_judge_pack
from .llm_smoke_results import render_llm_smoke_result
from .noisy_live_results import render_noisy_live_result


RESULT_SCHEMA_VERSION = "incident-generator.benchmark-result/v1"
COMPARISON_SCHEMA_VERSION = "incident-generator.benchmark-result-comparison/v1"
DEFAULT_COMPARISON_CREATED_AT = "2026-05-06T00:00:00Z"


class ResultComparisonError(ValueError):
    """Raised when benchmark-result payloads cannot be compared."""


BenchmarkResultComparisonError = ResultComparisonError


def build_result_comparison(
    root: Path,
    *,
    result_paths: list[Path] | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Build comparison metadata without the Markdown body."""

    payload = render_result_comparison(root, result_paths=result_paths, created_at=created_at)
    return {key: value for key, value in payload.items() if key != "markdown"}


def render_result_comparison_markdown(
    root: Path,
    *,
    result_paths: list[Path] | None = None,
    created_at: str | None = None,
    output_path: Path | None = None,
) -> str:
    """Render only the Markdown comparison table."""

    return render_result_comparison(
        root,
        result_paths=result_paths,
        created_at=created_at,
        output_path=output_path,
    )["markdown"]


def render_default_result_payloads(root: Path, *, created_at: str | None = None) -> list[dict[str, Any]]:
    """Render the checked local benchmark-result payloads used by the default comparison."""

    timestamp = created_at or DEFAULT_COMPARISON_CREATED_AT
    deterministic = render_deterministic_replay_result(root, created_at=timestamp)
    llm_smoke = render_llm_smoke_result(root, mode="both", created_at=timestamp)
    noisy_live = render_noisy_live_result(root, created_at=timestamp)
    external = run_agent_adapter_benchmark_set(
        root,
        judge_pack=select_judge_pack(root, "deterministic-local"),
        created_at=timestamp,
    )
    return [deterministic, llm_smoke, noisy_live, external]


def load_result_payloads(root: Path, result_paths: list[Path]) -> list[dict[str, Any]]:
    """Load benchmark-result payloads from JSON files."""

    payloads: list[dict[str, Any]] = []
    for path in result_paths:
        resolved = _resolve_path(root, path)
        payload = _load_json_object(resolved, error_cls=ResultComparisonError)
        _validate_payload(payload, source=str(path))
        payloads.append(payload)
    if not payloads:
        raise ResultComparisonError("at least one benchmark-result payload is required")
    return payloads


def render_result_comparison(
    root: Path,
    *,
    result_paths: list[Path] | None = None,
    payloads: list[Mapping[str, Any]] | None = None,
    created_at: str | None = None,
    output_path: Path | None = None,
) -> dict[str, Any]:
    """Render a comparison payload and Markdown table for benchmark-result entrants."""

    root = root.resolve()
    if payloads is not None and result_paths:
        raise ResultComparisonError("provide either payloads or result_paths, not both")
    selected_payloads = (
        [dict(payload) for payload in payloads]
        if payloads is not None
        else load_result_payloads(root, result_paths)
        if result_paths
        else render_default_result_payloads(root, created_at=created_at)
    )
    for index, payload in enumerate(selected_payloads, start=1):
        _validate_payload(payload, source=f"payload[{index}]")

    rows = _comparison_rows(root, selected_payloads)
    benchmark_sets = _benchmark_sets(selected_payloads)
    base_dir = _markdown_base_dir(root, output_path)
    markdown = _render_markdown(root, rows=rows, benchmark_sets=benchmark_sets, base_dir=base_dir)
    return {
        "schema_version": COMPARISON_SCHEMA_VERSION,
        "source_schema_version": RESULT_SCHEMA_VERSION,
        "payload_count": len(selected_payloads),
        "row_count": len(rows),
        "benchmark_sets": benchmark_sets,
        "rows": rows,
        "markdown": markdown,
    }


def write_result_comparison_markdown(
    root: Path,
    *,
    output: Path,
    result_paths: list[Path] | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Write a Markdown comparison table and return the comparison payload."""

    resolved_output = _resolve_path(root, output)
    payload = render_result_comparison(
        root,
        result_paths=result_paths,
        created_at=created_at,
        output_path=resolved_output,
    )
    resolved_output.parent.mkdir(parents=True, exist_ok=True)
    resolved_output.write_text(payload["markdown"], encoding="utf-8")
    return payload


def result_comparison_check_payload(
    root: Path,
    *,
    output: Path,
    result_paths: list[Path] | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    """Return a drift-check payload for a generated Markdown comparison table."""

    resolved_output = _resolve_path(root, output)
    payload = render_result_comparison(
        root,
        result_paths=result_paths,
        created_at=created_at,
        output_path=resolved_output,
    )
    expected = payload["markdown"]
    actual = resolved_output.read_text(encoding="utf-8") if resolved_output.is_file() else None
    return {
        "ok": actual == expected,
        "output": _relative_path(root.resolve(), resolved_output),
        "row_count": payload["row_count"],
        "payload_count": payload["payload_count"],
        "expected_sha256": _sha256_text(expected),
        "actual_sha256": _sha256_text(actual) if actual is not None else None,
        "missing": actual is None,
    }


def _comparison_rows(root: Path, payloads: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, dict[str, Any]] = {}
    for payload in payloads:
        set_id = _benchmark_set_id(payload)
        cases = _cases_by_id(payload)
        source_refs = _source_refs(payload)
        entrants = _entrants_by_id(payload)
        results = _result_rows(payload)
        for result in results:
            entrant_id = _string(result.get("entrant_id"))
            if not entrant_id:
                raise ResultComparisonError(f"result in {set_id} is missing entrant_id")
            entrant = entrants.get(entrant_id, {"entrant_id": entrant_id, "display_name": entrant_id})
            group = groups.setdefault(entrant_id, _empty_group(entrant))
            group["benchmark_set_ids"].add(set_id)
            case_id = _string(result.get("case_id"))
            if case_id:
                group["case_keys"].add(f"{set_id}:{case_id}")
            group["results"].append((payload, result, cases.get(case_id, {})))
            group["source_refs"].extend(source_refs)
    return [_row_from_group(root, entrant_id, group) for entrant_id, group in sorted(groups.items())]


def _row_from_group(root: Path, entrant_id: str, group: Mapping[str, Any]) -> dict[str, Any]:
    results = list(group["results"])
    passed_count = sum(1 for _, result, _ in results if result.get("state") == "passed")
    failed_count = sum(1 for _, result, _ in results if result.get("state") == "failed")
    blocked_count = sum(1 for _, result, _ in results if result.get("state") == "blocked")
    skipped_count = sum(1 for _, result, _ in results if result.get("state") == "skipped")
    error_count = sum(1 for _, result, _ in results if result.get("state") == "error")
    hypothesis = _hypothesis_summary(results)
    abstention = _abstention_summary(results)
    uncertainty = _uncertainty_summary(results)
    false_attribution = _false_attribution_summary(results)
    judge = _judge_summary(results)
    latency = _latency_summary(results)
    artifact_refs = _artifact_refs(root, group, results)
    entrant = group["entrant"]
    row = {
        "entrant_id": entrant_id,
        "display_name": _string(entrant.get("display_name")) or entrant_id,
        "agent_kind": _string(entrant.get("agent_kind")) or "unknown",
        "execution_mode": _string(entrant.get("execution_mode")) or "unknown",
        "agent_version": entrant.get("agent_version"),
        "model": entrant.get("model"),
        "judge_config": entrant.get("judge"),
        "benchmark_set_ids": sorted(group["benchmark_set_ids"]),
        "case_count": len(group["case_keys"]),
        "result_count": len(results),
        "passed_count": passed_count,
        "failed_count": failed_count,
        "blocked_count": blocked_count,
        "skipped_count": skipped_count,
        "error_count": error_count,
        "pass_rate": (passed_count / len(results)) if results else None,
        "hypothesis_preservation": hypothesis,
        "abstention_quality": abstention,
        "uncertainty_calibration": uncertainty,
        "false_attribution_guards": false_attribution,
        "judge_state": judge,
        "latency": latency,
        "artifact_refs": artifact_refs,
    }
    return row


def _empty_group(entrant: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "entrant": dict(entrant),
        "benchmark_set_ids": set(),
        "case_keys": set(),
        "results": [],
        "source_refs": [],
    }


def _hypothesis_summary(results: list[tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]]) -> dict[str, int]:
    checks_total = 0
    checks_passed = 0
    expected_total = 0
    matched_total = 0
    missing_total = 0
    unexpected_total = 0
    for _, result, case in results:
        checks_total += 1
        if _score_bool(result, "hypothesis_pass", _diagnosis_missing(result) == 0):
            checks_passed += 1
        diagnosis = _mapping(result.get("diagnosis"))
        expected = _string_list(_mapping(case.get("expectations")).get("expected_hypotheses"))
        matched = _string_list(diagnosis.get("matched_expected_hypotheses"))
        missing = _string_list(diagnosis.get("missing_expected_hypotheses"))
        unexpected = _string_list(diagnosis.get("unexpected_hypotheses"))
        expected_count = len(expected) if expected else len(matched) + len(missing)
        expected_total += expected_count
        matched_total += len(matched)
        missing_total += len(missing)
        unexpected_total += len(unexpected)
    return {
        "checks_passed": checks_passed,
        "checks_total": checks_total,
        "matched_expected_count": matched_total,
        "expected_count": expected_total,
        "missing_expected_count": missing_total,
        "unexpected_count": unexpected_total,
    }


def _abstention_summary(results: list[tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]]) -> dict[str, int]:
    checks_total = 0
    checks_passed = 0
    required_count = 0
    required_observed_count = 0
    unexpected_abstention_count = 0
    for _, result, case in results:
        checks_total += 1
        discipline = _mapping(result.get("evidence_discipline"))
        required = _bool_or_case(discipline.get("abstention_required"), case, "required_abstention")
        abstained = discipline.get("abstained") is True
        if required:
            required_count += 1
            if abstained:
                required_observed_count += 1
        elif abstained:
            unexpected_abstention_count += 1
        fallback_pass = abstained if required else not abstained
        if _score_bool(result, "abstention_pass", fallback_pass):
            checks_passed += 1
    return {
        "checks_passed": checks_passed,
        "checks_total": checks_total,
        "required_count": required_count,
        "required_observed_count": required_observed_count,
        "unexpected_abstention_count": unexpected_abstention_count,
    }


def _uncertainty_summary(results: list[tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]]) -> dict[str, int]:
    checks_total = 0
    checks_passed = 0
    required_count = 0
    required_observed_count = 0
    observed_count = 0
    for _, result, case in results:
        checks_total += 1
        discipline = _mapping(result.get("evidence_discipline"))
        required = _bool_or_case(discipline.get("uncertainty_required"), case, "uncertainty_expected")
        stated = discipline.get("uncertainty_stated") is True
        if required:
            required_count += 1
            if stated:
                required_observed_count += 1
        if stated:
            observed_count += 1
        fallback_pass = stated if required else True
        if _score_bool(result, "uncertainty_pass", fallback_pass):
            checks_passed += 1
    return {
        "checks_passed": checks_passed,
        "checks_total": checks_total,
        "required_count": required_count,
        "required_observed_count": required_observed_count,
        "observed_count": observed_count,
    }


def _false_attribution_summary(
    results: list[tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]],
) -> dict[str, int]:
    checks_total = 0
    checks_passed = 0
    observed_count = 0
    guarded_result_count = 0
    for _, result, case in results:
        checks_total += 1
        discipline = _mapping(result.get("evidence_discipline"))
        observed = len(_string_list(discipline.get("false_attribution_observed"))) + len(
            _string_list(discipline.get("forbidden_hypotheses_observed"))
        )
        guards = _string_list(_mapping(case.get("expectations")).get("false_attribution_guards")) + _string_list(
            _mapping(case.get("expectations")).get("forbidden_hypotheses")
        )
        if guards:
            guarded_result_count += 1
        observed_count += observed
        if _score_bool(result, "false_attribution_pass", observed == 0):
            checks_passed += 1
    return {
        "checks_passed": checks_passed,
        "checks_total": checks_total,
        "guarded_result_count": guarded_result_count,
        "observed_count": observed_count,
    }


def _judge_summary(results: list[tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]]) -> dict[str, Any]:
    statuses: Counter[str] = Counter()
    verdicts: Counter[str] = Counter()
    kinds: set[str] = set()
    separate_family_required_count = 0
    separate_family_ok_count = 0
    for _, result, _ in results:
        judge = result.get("judge_outcome")
        if not isinstance(judge, Mapping):
            statuses["not_requested"] += 1
            continue
        status = _string(judge.get("status")) or "unknown"
        verdict = _string(judge.get("verdict")) or "none"
        kind = _string(judge.get("judge_kind"))
        statuses[status] += 1
        verdicts[verdict] += 1
        if kind:
            kinds.add(kind)
        if judge.get("separate_family_ok") is not None:
            separate_family_required_count += 1
            if judge.get("separate_family_ok") is True:
                separate_family_ok_count += 1
    total = len(results)
    return {
        "statuses": dict(sorted(statuses.items())),
        "verdicts": dict(sorted(verdicts.items())),
        "judge_kinds": sorted(kinds),
        "executed_count": statuses.get("executed", 0),
        "passed_count": verdicts.get("pass", 0),
        "total_count": total,
        "separate_family_required_count": separate_family_required_count,
        "separate_family_ok_count": separate_family_ok_count,
    }


def _latency_summary(results: list[tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]]) -> dict[str, int | None]:
    durations = sorted(
        int(round(duration))
        for _, result, _ in results
        for duration in [_number(result.get("duration_ms"))]
        if duration is not None and duration >= 0
    )
    if not durations:
        return {"count": 0, "average_ms": None, "p95_ms": None, "max_ms": None}
    p95_index = max(0, math.ceil(0.95 * len(durations)) - 1)
    return {
        "count": len(durations),
        "average_ms": int(round(sum(durations) / len(durations))),
        "p95_ms": durations[p95_index],
        "max_ms": durations[-1],
    }


def _artifact_refs(
    root: Path,
    group: Mapping[str, Any],
    results: list[tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]],
) -> list[dict[str, str | None]]:
    refs: list[dict[str, str | None]] = []
    refs.extend(ref for ref in group.get("source_refs", []) if isinstance(ref, Mapping))
    for _, result, case in results:
        output_ref = _string(result.get("agent_output_ref"))
        if output_ref:
            refs.append({"kind": "agent_output", "ref": output_ref, "sha256": None})
        judge = result.get("judge_outcome")
        if isinstance(judge, Mapping):
            rationale_ref = _string(judge.get("rationale_ref"))
            if rationale_ref:
                refs.append({"kind": "judge_rationale", "ref": rationale_ref, "sha256": None})
        incident = case.get("generated_incident") if isinstance(case, Mapping) else None
        if isinstance(incident, Mapping):
            refs.extend(ref for ref in incident.get("artifact_refs", []) if isinstance(ref, Mapping))
    unique: list[dict[str, str | None]] = []
    seen: set[str] = set()
    for ref in refs:
        ref_text = _string(ref.get("ref"))
        if not ref_text:
            continue
        if ref_text in seen:
            continue
        seen.add(ref_text)
        kind = _string(ref.get("kind")) or "artifact"
        unique.append(
            {
                "kind": kind,
                "ref": ref_text,
                "sha256": _string(ref.get("sha256")) or None,
            }
        )
    return unique


def _render_markdown(
    root: Path,
    *,
    rows: list[Mapping[str, Any]],
    benchmark_sets: list[str],
    base_dir: Path,
) -> str:
    lines = [
        "# Benchmark Result Comparison",
        "",
        "Generated from `incident-generator.benchmark-result/v1` payloads. The default view combines the checked deterministic replay, fixture/live LLM smoke, noisy live artifact replay, and external adapter benchmark-set results without rerunning live providers.",
        "",
        f"Benchmark sets: {', '.join(f'`{value}`' for value in benchmark_sets)}.",
        "",
        "| Entrant | Kind | Benchmarks | Results | Pass rate | Hypotheses | Abstention | Uncertainty | False attribution | Judge state | Latency | Artifact links |",
        "| --- | --- | --- | ---: | ---: | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                _escape_table_cell(value)
                for value in [
                    _display_name(row),
                    _kind_cell(row),
                    ", ".join(f"`{value}`" for value in row["benchmark_set_ids"]),
                    f"{row['passed_count']}/{row['result_count']}",
                    _format_rate(row["passed_count"], row["result_count"]),
                    _format_hypothesis(row["hypothesis_preservation"]),
                    _format_abstention(row["abstention_quality"]),
                    _format_uncertainty(row["uncertainty_calibration"]),
                    _format_false_attribution(row["false_attribution_guards"]),
                    _format_judge(row["judge_state"]),
                    _format_latency(row["latency"]),
                    _format_artifact_links(root, row["artifact_refs"], base_dir),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "Artifact refs are taken from benchmark-set source refs, case artifact refs, agent output refs, and judge rationale refs in the schema payloads. Refs to retained local `.tmp` or `benchmark-artifacts` artifacts are shown as code spans when they are not portable checked files.",
            "",
        ]
    )
    return "\n".join(lines)


def _format_hypothesis(summary: Mapping[str, int]) -> str:
    checks = _format_fraction(summary["checks_passed"], summary["checks_total"])
    expected = _format_fraction(summary["matched_expected_count"], summary["expected_count"])
    missing = summary["missing_expected_count"]
    unexpected = summary["unexpected_count"]
    return f"{checks} checks; {expected} expected; missing {missing}; unexpected {unexpected}"


def _format_abstention(summary: Mapping[str, int]) -> str:
    checks = _format_fraction(summary["checks_passed"], summary["checks_total"])
    required = _format_fraction(summary["required_observed_count"], summary["required_count"])
    unexpected = summary["unexpected_abstention_count"]
    return f"{checks} checks; required {required}; unexpected {unexpected}"


def _format_uncertainty(summary: Mapping[str, int]) -> str:
    checks = _format_fraction(summary["checks_passed"], summary["checks_total"])
    required = _format_fraction(summary["required_observed_count"], summary["required_count"])
    observed = summary["observed_count"]
    return f"{checks} checks; required {required}; stated {observed}"


def _format_false_attribution(summary: Mapping[str, int]) -> str:
    checks = _format_fraction(summary["checks_passed"], summary["checks_total"])
    guarded = summary["guarded_result_count"]
    observed = summary["observed_count"]
    return f"{checks} checks; guarded {guarded}; observed {observed}"


def _format_judge(summary: Mapping[str, Any]) -> str:
    total = int(summary["total_count"])
    executed = _format_fraction(int(summary["executed_count"]), total)
    passed = _format_fraction(int(summary["passed_count"]), total)
    statuses = ", ".join(f"{key} {value}" for key, value in summary["statuses"].items()) or "none"
    kinds = ", ".join(summary["judge_kinds"]) or "none"
    separate = ""
    if summary["separate_family_required_count"]:
        separate = f"; separate-family {_format_fraction(summary['separate_family_ok_count'], summary['separate_family_required_count'])}"
    return f"executed {executed}; pass {passed}; {statuses}; {kinds}{separate}"


def _format_latency(summary: Mapping[str, int | None]) -> str:
    if not summary["count"]:
        return "n/a"
    return f"avg {summary['average_ms']} ms; p95 {summary['p95_ms']} ms; max {summary['max_ms']} ms"


def _format_artifact_links(root: Path, refs: list[Mapping[str, str | None]], base_dir: Path) -> str:
    if not refs:
        return "none"
    rendered: list[str] = []
    for ref in refs[:4]:
        label = (_string(ref.get("kind")) or "artifact").replace("_", " ")
        rendered.append(_artifact_link(root, _string(ref.get("ref")), label=label, base_dir=base_dir))
    if len(refs) > 4:
        rendered.append(f"+{len(refs) - 4} refs")
    return "; ".join(rendered)


def _artifact_link(root: Path, ref: str, *, label: str, base_dir: Path) -> str:
    if not ref:
        return "none"
    path_text, anchor = _split_anchor(ref)
    if _is_portable_checked_ref(path_text):
        target = _resolve_path(root, Path(path_text))
        if target.is_file():
            relative = os.path.relpath(target, base_dir).replace(os.sep, "/")
            return f"[{_escape_link_label(label)}]({relative}{anchor})"
    if ref.startswith(("http://", "https://")):
        return f"[{_escape_link_label(label)}]({ref})"
    return f"`{_escape_code(ref)}`"


def _is_portable_checked_ref(path_text: str) -> bool:
    if not path_text:
        return False
    if Path(path_text).is_absolute():
        return False
    first = Path(path_text).parts[0] if Path(path_text).parts else ""
    return first not in {".tmp", "benchmark-artifacts", "tmp", "var"}


def _display_name(row: Mapping[str, Any]) -> str:
    return f"{row['display_name']} (`{row['entrant_id']}`)"


def _kind_cell(row: Mapping[str, Any]) -> str:
    model = _model_label(row.get("model"))
    mode = row.get("execution_mode") or "unknown"
    return f"`{row['agent_kind']}` / `{mode}` / {model}"


def _model_label(model: Any) -> str:
    if not isinstance(model, Mapping):
        return "`no model`"
    provider = _string(model.get("provider")) or "unknown-provider"
    family = _string(model.get("model_family")) or "unknown-family"
    model_id = _string(model.get("model_id")) or "unknown-model"
    return f"`{provider}:{family}:{model_id}`"


def _format_rate(passed: int, total: int) -> str:
    if total <= 0:
        return "n/a"
    return f"{passed / total * 100:.1f}%"


def _format_fraction(numerator: int, denominator: int) -> str:
    return f"{numerator}/{denominator}" if denominator else "0/0"


def _benchmark_sets(payloads: list[Mapping[str, Any]]) -> list[str]:
    values: list[str] = []
    for payload in payloads:
        set_id = _benchmark_set_id(payload)
        if set_id not in values:
            values.append(set_id)
    return values


def _benchmark_set_id(payload: Mapping[str, Any]) -> str:
    benchmark_set = payload.get("benchmark_set")
    if not isinstance(benchmark_set, Mapping):
        raise ResultComparisonError("benchmark-result payload missing benchmark_set")
    set_id = _string(benchmark_set.get("benchmark_set_id"))
    if not set_id:
        raise ResultComparisonError("benchmark-result payload missing benchmark_set_id")
    return set_id


def _cases_by_id(payload: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    cases = payload.get("cases")
    if not isinstance(cases, list):
        raise ResultComparisonError(f"{_benchmark_set_id(payload)} missing cases list")
    by_id: dict[str, Mapping[str, Any]] = {}
    for index, case in enumerate(cases):
        if not isinstance(case, Mapping):
            raise ResultComparisonError(f"{_benchmark_set_id(payload)} cases[{index}] must be an object")
        case_id = _string(case.get("case_id"))
        if not case_id:
            raise ResultComparisonError(f"{_benchmark_set_id(payload)} cases[{index}] missing case_id")
        by_id[case_id] = case
    return by_id


def _entrants_by_id(payload: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    entrants = payload.get("entrants")
    if not isinstance(entrants, list):
        raise ResultComparisonError(f"{_benchmark_set_id(payload)} missing entrants list")
    by_id: dict[str, Mapping[str, Any]] = {}
    for index, entrant in enumerate(entrants):
        if not isinstance(entrant, Mapping):
            raise ResultComparisonError(f"{_benchmark_set_id(payload)} entrants[{index}] must be an object")
        entrant_id = _string(entrant.get("entrant_id"))
        if not entrant_id:
            raise ResultComparisonError(f"{_benchmark_set_id(payload)} entrants[{index}] missing entrant_id")
        by_id[entrant_id] = entrant
    return by_id


def _result_rows(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    results = payload.get("results")
    if not isinstance(results, list):
        raise ResultComparisonError(f"{_benchmark_set_id(payload)} missing results list")
    parsed: list[Mapping[str, Any]] = []
    for index, result in enumerate(results):
        if not isinstance(result, Mapping):
            raise ResultComparisonError(f"{_benchmark_set_id(payload)} results[{index}] must be an object")
        parsed.append(result)
    return parsed


def _source_refs(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    benchmark_set = payload.get("benchmark_set")
    if not isinstance(benchmark_set, Mapping):
        return []
    refs = benchmark_set.get("source_refs")
    return [ref for ref in refs if isinstance(ref, Mapping)] if isinstance(refs, list) else []


def _validate_payload(payload: Mapping[str, Any], *, source: str) -> None:
    if payload.get("schema_version") != RESULT_SCHEMA_VERSION:
        raise ResultComparisonError(f"{source} has unsupported schema_version: {payload.get('schema_version')}")
    for field in ("benchmark_set", "cases", "entrants", "results", "aggregate"):
        if field not in payload:
            raise ResultComparisonError(f"{source} missing required field: {field}")


def _score_bool(result: Mapping[str, Any], field: str, fallback: bool) -> bool:
    scoring = result.get("scoring")
    if isinstance(scoring, Mapping) and isinstance(scoring.get(field), bool):
        return scoring[field]
    return fallback


def _diagnosis_missing(result: Mapping[str, Any]) -> int:
    diagnosis = result.get("diagnosis")
    if not isinstance(diagnosis, Mapping):
        return 1
    return len(_string_list(diagnosis.get("missing_expected_hypotheses")))


def _bool_or_case(value: Any, case: Mapping[str, Any], expectation_field: str) -> bool:
    if isinstance(value, bool):
        return value
    expectations = case.get("expectations")
    return isinstance(expectations, Mapping) and expectations.get(expectation_field) is True


def _markdown_base_dir(root: Path, output_path: Path | None) -> Path:
    if output_path is None:
        return root
    resolved = _resolve_path(root, output_path)
    return resolved.parent.resolve()


def _split_anchor(ref: str) -> tuple[str, str]:
    if "#" not in ref:
        return ref, ""
    path_text, anchor = ref.split("#", 1)
    return path_text, f"#{anchor}"


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _string(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str) and item]


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _escape_table_cell(value: Any) -> str:
    text = str(value)
    return text.replace("\n", "<br>").replace("|", "\\|")


def _escape_link_label(value: str) -> str:
    return value.replace("[", "\\[").replace("]", "\\]")


def _escape_code(value: str) -> str:
    return value.replace("`", "'")
