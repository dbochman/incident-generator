"""Command line interface for the incident generator."""

from __future__ import annotations

import argparse
import itertools
import json
import os
import random
import subprocess
import sys
from collections import Counter, defaultdict
from math import comb
from pathlib import Path
from typing import Any

from .adversarial_combos import (
    DEFAULT_ADVERSARIAL_COMBOS_RELATIVE,
    render_adversarial_combo_report,
)
from .artifact_registry import (
    ArtifactRegistryError,
    append_registry_entry,
    parse_env_assignments,
    registry_check_payload,
    registry_markdown_check_payload,
    render_registry_markdown,
    write_registry_markdown,
)
from .benchmark_runner import (
    BenchmarkRunnerError,
    DEFAULT_AGENT_ADAPTER_EXCHANGE_RELATIVE,
    parse_evidence_role_expectations,
    run_agent_adapter_benchmark,
)
from .benchmark_previews import (
    DEFAULT_PAIR_PREVIEW_RELATIVE,
    DEFAULT_TRIPLE_PREVIEW_RELATIVE,
    render_random_pair_fixture_preview,
    render_triple_benchmark_fixture_preview,
)
from .checks import check_fixture_hygiene, check_markdown_links, findings_payload
from .confidence_calibration import (
    DEFAULT_CONFIDENCE_CALIBRATION_RELATIVE,
    render_confidence_calibration_report,
)
from .conflicting_signal_combos import (
    DEFAULT_CONFLICTING_SIGNAL_COMBOS_RELATIVE,
    render_conflicting_signal_combo_report,
)
from .evidence_discipline_combos import (
    DEFAULT_EVIDENCE_DISCIPLINE_COMBOS_RELATIVE,
    render_evidence_discipline_combo_report,
)
from .noisy_fixtures import render_noisy_fixture_bundle
from .noisy_partial_failures import DEFAULT_PACK_RELATIVE, render_noisy_partial_failure_pack
from .noisy_smoke import DEFAULT_SMOKE_RELATIVE, render_noisy_smoke_report
from .progress import OperatorProgressReporter, default_artifact_dir
from .release import write_release_manifest
from .recovery_benchmarks import (
    DEFAULT_RECOVERY_BENCHMARK_RELATIVE,
    render_recovery_after_diagnosis_benchmark,
)
from .scenarios import (
    COLLECTION_MODES,
    apply_failure_classification,
    build_catalog_report,
    combination_compatibility_report,
    default_variant_selection,
    list_scenario_packages,
    load_scenario_package,
    parse_variant_args,
    scenarios_are_compatible_for_mode,
    stand_up_combinatorial_incident_environment,
    stand_up_incident_environment,
    validate_scenario_package,
)
from .temporal_benchmarks import DEFAULT_TEMPORAL_MODEL_RELATIVE, render_temporal_benchmark_model


MAX_ENUMERATED_RANDOM_COMBINATIONS = 200_000
WARM_KIND_ENV = {
    "SRE_AGENT_KIND_KEEP_CLUSTER": "1",
    "SRE_AGENT_OBSERVABILITY_REUSE_READY": "1",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="incident-generator", description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd(), help="Project root containing scenarios/ and harness/")
    subparsers = parser.add_subparsers(dest="command", required=True)

    list_parser = subparsers.add_parser("list", help="List scenario packages")
    list_parser.add_argument("--json", action="store_true", help="Emit JSON")

    catalog_parser = subparsers.add_parser("catalog", help="Report scenario catalog coverage and live readiness")
    catalog_parser.add_argument("--json", action="store_true", help="Emit JSON")

    validate_parser = subparsers.add_parser("validate", help="Validate scenario packages")
    validate_parser.add_argument("--scenario", type=Path, action="append", help="Validate one scenario path")
    validate_parser.add_argument("--json", action="store_true", help="Emit JSON")

    plan_parser = subparsers.add_parser("plan", help="Preview combinatorial compatibility without starting infrastructure")
    plan_parser.add_argument("--scenario", type=Path, action="append")
    plan_parser.add_argument(
        "--combination",
        action="append",
        help="Comma-separated scenario paths that form one explicit combination; repeat for a batch",
    )
    plan_parser.add_argument(
        "--random-compatible-combinations",
        type=int,
        help="Preview N random same-archetype scenario combinations from the catalog",
    )
    plan_parser.add_argument(
        "--random-combination-size",
        type=int,
        default=2,
        help="Number of scenarios per random compatible combination; defaults to 2",
    )
    plan_parser.add_argument(
        "--random-archetype",
        action="append",
        help="Restrict random compatible combinations to one environment_archetype; repeat to allow several",
    )
    plan_parser.add_argument(
        "--random-seed",
        type=int,
        help="Seed random compatible combination selection for reproducible planner previews",
    )
    plan_parser.add_argument("--collection-mode", choices=sorted(COLLECTION_MODES), default="real")
    plan_parser.add_argument("--json", action="store_true", help="Emit JSON")

    run_parser = subparsers.add_parser("run", help="Generate one incident environment")
    run_parser.add_argument("--scenario", type=Path, action="append")
    run_parser.add_argument(
        "--combination",
        action="append",
        help="Comma-separated scenario paths that form one explicit combination; repeat for a batch",
    )
    run_parser.add_argument(
        "--random-compatible-combinations",
        type=int,
        help="Generate N random same-archetype scenario combinations from the catalog",
    )
    run_parser.add_argument(
        "--random-combination-size",
        type=int,
        default=2,
        help="Number of scenarios per random compatible combination; defaults to 2",
    )
    run_parser.add_argument(
        "--random-archetype",
        action="append",
        help="Restrict random compatible combinations to one environment_archetype; repeat to allow several",
    )
    run_parser.add_argument(
        "--random-seed",
        type=int,
        help="Seed random compatible combination selection for reproducible smoke batches",
    )
    run_parser.add_argument("--variant", action="append", dest="variants", help="Variant override as axis=value")
    run_parser.add_argument("--collection-mode", choices=sorted(COLLECTION_MODES))
    run_parser.add_argument("--incident-id")
    run_parser.add_argument("--incident-session-id", default="incident-generator-run")
    run_parser.add_argument("--require-tools", action="store_true", help="Do not fall back to fixture mode if real tools are absent")
    run_parser.add_argument(
        "--warm-kind",
        action="store_true",
        help="Reuse one kind cluster and ready observability stack across a real-mode kind batch, then delete it at the end",
    )
    run_parser.add_argument("--hold", action="store_true", help="Keep real infrastructure up until interrupted, then tear down")
    run_parser.add_argument("--hold-seconds", type=float, help="Keep real infrastructure up for N seconds, then tear down")
    progress_group = run_parser.add_mutually_exclusive_group()
    progress_group.add_argument("--progress", action="store_true", help="Emit human-readable progress events to stderr")
    progress_group.add_argument("--progress-json", action="store_true", help="Emit newline-delimited JSON progress events to stderr")
    run_parser.add_argument(
        "--progress-artifact-dir",
        type=Path,
        help="Write progress artifacts to this directory; defaults to .tmp/incidents/<session> when progress is enabled",
    )
    run_parser.add_argument("--json", action="store_true", help="Emit JSON")

    noisy_parser = subparsers.add_parser("noisy-fixture", help="Render a deterministic noisy fixture bundle manifest")
    noisy_parser.add_argument("--scenario", type=Path, required=True, help="Scenario package path")
    noisy_parser.add_argument("--seed", type=int, help="Deterministic noise source selection seed")
    noisy_parser.add_argument("--max-noise-sources", type=int, help="Limit selected noise sources deterministically")
    noisy_parser.add_argument("--output", type=Path, help="Write JSON manifest to this path")
    noisy_parser.add_argument("--json", action="store_true", help="Emit JSON")

    noisy_smoke_parser = subparsers.add_parser("noisy-smoke", help="Render a deterministic noisy smoke report")
    noisy_smoke_parser.add_argument(
        "--smoke",
        type=Path,
        default=DEFAULT_SMOKE_RELATIVE,
        help="Noisy smoke plan path",
    )
    noisy_smoke_parser.add_argument("--seed", type=int, help="Deterministic noise source selection seed")
    noisy_smoke_parser.add_argument("--max-noise-sources", type=int, help="Limit selected noise sources deterministically")
    noisy_smoke_parser.add_argument("--output", type=Path, help="Write JSON report to this path")
    noisy_smoke_parser.add_argument("--json", action="store_true", help="Emit JSON")

    noisy_partial_parser = subparsers.add_parser(
        "noisy-partial-failures",
        help="Render a deterministic noisy partial-failure pack report",
    )
    noisy_partial_parser.add_argument(
        "--pack",
        type=Path,
        default=DEFAULT_PACK_RELATIVE,
        help="Noisy partial-failure pack path",
    )
    noisy_partial_parser.add_argument("--seed", type=int, help="Deterministic noise source selection seed")
    noisy_partial_parser.add_argument("--max-noise-sources", type=int, help="Limit selected noise sources deterministically")
    noisy_partial_parser.add_argument("--output", type=Path, help="Write JSON report to this path")
    noisy_partial_parser.add_argument("--json", action="store_true", help="Emit JSON")

    triple_preview_parser = subparsers.add_parser(
        "triple-preview",
        help="Render a deterministic fixture-mode triple benchmark preview",
    )
    triple_preview_parser.add_argument(
        "--preview",
        type=Path,
        default=DEFAULT_TRIPLE_PREVIEW_RELATIVE,
        help="Triple preview plan path",
    )
    triple_preview_parser.add_argument("--seed", type=int, help="Override the deterministic preview seed")
    triple_preview_parser.add_argument("--selected-count", type=int, help="Override the number of selected triples")
    triple_preview_parser.add_argument("--output", type=Path, help="Write JSON report to this path")
    triple_preview_parser.add_argument("--json", action="store_true", help="Emit JSON")

    pair_preview_parser = subparsers.add_parser(
        "pair-preview",
        help="Render a deterministic fixture preview of real-compatible random pairs",
    )
    pair_preview_parser.add_argument(
        "--preview",
        type=Path,
        default=DEFAULT_PAIR_PREVIEW_RELATIVE,
        help="Random pair preview plan path",
    )
    pair_preview_parser.add_argument("--seed", type=int, help="Override the deterministic preview seed")
    pair_preview_parser.add_argument("--selected-count", type=int, help="Override the number of selected pairs")
    pair_preview_parser.add_argument("--output", type=Path, help="Write JSON report to this path")
    pair_preview_parser.add_argument("--json", action="store_true", help="Emit JSON")

    temporal_model_parser = subparsers.add_parser(
        "temporal-model",
        help="Render a temporal incident benchmark model report",
    )
    temporal_model_parser.add_argument(
        "--model",
        type=Path,
        default=DEFAULT_TEMPORAL_MODEL_RELATIVE,
        help="Temporal benchmark model path",
    )
    temporal_model_parser.add_argument("--output", type=Path, help="Write JSON report to this path")
    temporal_model_parser.add_argument("--json", action="store_true", help="Emit JSON")

    recovery_benchmark_parser = subparsers.add_parser(
        "recovery-benchmark",
        help="Render a recovery-after-diagnosis benchmark report",
    )
    recovery_benchmark_parser.add_argument(
        "--benchmark",
        type=Path,
        default=DEFAULT_RECOVERY_BENCHMARK_RELATIVE,
        help="Recovery benchmark definition path",
    )
    recovery_benchmark_parser.add_argument("--output", type=Path, help="Write JSON report to this path")
    recovery_benchmark_parser.add_argument("--json", action="store_true", help="Emit JSON")

    adversarial_combo_parser = subparsers.add_parser(
        "adversarial-combos",
        help="Render fixture-mode adversarial benchmark combinations",
    )
    adversarial_combo_parser.add_argument(
        "--combos",
        type=Path,
        default=DEFAULT_ADVERSARIAL_COMBOS_RELATIVE,
        help="Adversarial combo definition path",
    )
    adversarial_combo_parser.add_argument("--output", type=Path, help="Write JSON report to this path")
    adversarial_combo_parser.add_argument("--json", action="store_true", help="Emit JSON")

    evidence_discipline_parser = subparsers.add_parser(
        "evidence-discipline-combos",
        help="Render fixture-mode missing-evidence and red-herring benchmark combinations",
    )
    evidence_discipline_parser.add_argument(
        "--combos",
        type=Path,
        default=DEFAULT_EVIDENCE_DISCIPLINE_COMBOS_RELATIVE,
        help="Evidence-discipline combo definition path",
    )
    evidence_discipline_parser.add_argument("--output", type=Path, help="Write JSON report to this path")
    evidence_discipline_parser.add_argument("--json", action="store_true", help="Emit JSON")

    conflicting_signal_parser = subparsers.add_parser(
        "conflicting-signal-combos",
        help="Render fixture-mode conflicting-signal benchmark combinations",
    )
    conflicting_signal_parser.add_argument(
        "--combos",
        type=Path,
        default=DEFAULT_CONFLICTING_SIGNAL_COMBOS_RELATIVE,
        help="Conflicting-signal combo definition path",
    )
    conflicting_signal_parser.add_argument("--output", type=Path, help="Write JSON report to this path")
    conflicting_signal_parser.add_argument("--json", action="store_true", help="Emit JSON")

    confidence_calibration_parser = subparsers.add_parser(
        "confidence-calibration",
        help="Render the checked deterministic-vs-live confidence calibration report",
    )
    confidence_calibration_parser.add_argument(
        "--calibration",
        type=Path,
        default=DEFAULT_CONFIDENCE_CALIBRATION_RELATIVE,
        help="Confidence calibration definition path",
    )
    confidence_calibration_parser.add_argument("--output", type=Path, help="Write JSON report to this path")
    confidence_calibration_parser.add_argument("--json", action="store_true", help="Emit JSON")

    benchmark_runner_parser = subparsers.add_parser(
        "benchmark-runner",
        help="Run or replay an external agent adapter exchange and emit benchmark results",
    )
    benchmark_runner_parser.add_argument(
        "--exchange",
        type=Path,
        default=DEFAULT_AGENT_ADAPTER_EXCHANGE_RELATIVE,
        help="Agent adapter exchange JSON path",
    )
    benchmark_runner_parser.add_argument(
        "--adapter-command",
        help="Optional local command to run with the adapter request JSON on stdin; stdout must be response JSON",
    )
    benchmark_runner_parser.add_argument(
        "--expected-hypothesis",
        action="append",
        required=True,
        help="Expected hypothesis for result scoring; repeat for multiple hypotheses",
    )
    benchmark_runner_parser.add_argument(
        "--forbidden-hypothesis",
        action="append",
        help="Forbidden hypothesis text for false-attribution scoring; repeat as needed",
    )
    benchmark_runner_parser.add_argument(
        "--false-attribution-guard",
        action="append",
        help="False-attribution guard to copy into the result payload; repeat as needed",
    )
    benchmark_runner_parser.add_argument(
        "--evidence-role",
        action="append",
        help="Runner-only evidence role expectation as ROLE=COUNT; repeat as needed",
    )
    benchmark_runner_parser.add_argument("--required-abstention", action="store_true", help="Require the adapter to abstain")
    benchmark_runner_parser.add_argument(
        "--uncertainty-expected",
        action="store_true",
        help="Require an explicit uncertainty statement",
    )
    benchmark_runner_parser.add_argument(
        "--scenario-id",
        action="append",
        help="Scenario id to record in the result payload; defaults to the adapter request case id",
    )
    benchmark_runner_parser.add_argument(
        "--archetype",
        default="unknown",
        choices=["fixture", "kind", "linux-vm", "mixed", "unknown"],
        help="Generated incident archetype to record in the result payload",
    )
    benchmark_runner_parser.add_argument("--result-id", help="Result id override")
    benchmark_runner_parser.add_argument("--created-at", help="Created-at timestamp override for deterministic tests")
    benchmark_runner_parser.add_argument("--output", type=Path, help="Write benchmark-result JSON to this path")
    benchmark_runner_parser.add_argument("--json", action="store_true", help="Emit JSON")

    doctor_parser = subparsers.add_parser("doctor", help="Show local tool availability for real modes")
    doctor_parser.add_argument("--json", action="store_true", help="Emit JSON")

    docs_parser = subparsers.add_parser("docs-check", help="Check repository Markdown links")
    docs_parser.add_argument("--json", action="store_true", help="Emit JSON")

    hygiene_parser = subparsers.add_parser("fixture-hygiene", help="Scan fixture files for unallowlisted secrets")
    hygiene_parser.add_argument("--json", action="store_true", help="Emit JSON")

    manifest_parser = subparsers.add_parser("release-manifest", help="Generate a release manifest")
    manifest_parser.add_argument("--output", type=Path, default=Path("dist/release-manifest.json"), help="Manifest output path")
    manifest_parser.add_argument("--artifact-dir", type=Path, default=Path("dist"), help="Directory containing built artifacts")
    manifest_parser.add_argument("--json", action="store_true", help="Emit JSON")

    registry_parser = subparsers.add_parser("artifact-registry", help="Manage benchmark artifact registry entries")
    registry_subparsers = registry_parser.add_subparsers(dest="registry_command", required=True)
    registry_add_parser = registry_subparsers.add_parser("add", help="Append one retained benchmark run to a registry")
    registry_add_parser.add_argument("--registry", type=Path, required=True, help="Registry JSON path to create or append")
    registry_add_parser.add_argument("--artifact-dir", type=Path, required=True, help="Directory containing result/progress artifacts")
    registry_add_parser.add_argument("--benchmark-set-id", required=True, help="Logical benchmark set id")
    registry_add_parser.add_argument("--run-id", help="Stable run id; defaults to the result incident session or artifact directory name")
    registry_add_parser.add_argument("--seed", type=int, help="Random seed used for scenario selection")
    registry_add_parser.add_argument(
        "--command",
        dest="benchmark_command",
        required=True,
        help="Original benchmark command line, parsed with shell-style quoting",
    )
    registry_add_parser.add_argument("--env", action="append", help="Environment override to record as KEY=VALUE; repeat as needed")
    registry_add_parser.add_argument("--host-profile", default="unknown", help="Resource profile id, such as kind/warm-batch")
    registry_add_parser.add_argument("--docker-host-kind", choices=["local", "ssh", "none", "unknown"])
    registry_add_parser.add_argument("--docker-host", help="Docker host used for the benchmark, for example ssh://host")
    registry_add_parser.add_argument("--architecture", help="Host architecture")
    registry_add_parser.add_argument("--cpu-count", type=int, help="Host CPU count")
    registry_add_parser.add_argument("--memory-bytes", type=int, help="Host memory in bytes")
    registry_add_parser.add_argument("--docker-data-root-free-bytes", type=int, help="Free bytes in Docker data root")
    registry_add_parser.add_argument("--agent-replay-summary", type=Path, help="Optional validated-combo agent summary.json")
    registry_add_parser.add_argument("--created-at", help="Entry timestamp override, primarily for deterministic tests")
    registry_add_parser.add_argument("--json", action="store_true", help="Emit JSON")
    registry_check_parser = registry_subparsers.add_parser("check", help="Validate retained benchmark artifacts and hashes")
    registry_check_parser.add_argument("--registry", type=Path, required=True, help="Registry JSON path to validate")
    registry_check_parser.add_argument("--json", action="store_true", help="Emit JSON")
    registry_markdown_parser = registry_subparsers.add_parser("markdown", help="Render a Markdown artifact registry view")
    registry_markdown_parser.add_argument("--registry", type=Path, required=True, help="Registry JSON path to render")
    registry_markdown_output_group = registry_markdown_parser.add_mutually_exclusive_group()
    registry_markdown_output_group.add_argument("--output", type=Path, help="Markdown output path to write")
    registry_markdown_output_group.add_argument("--check-output", type=Path, help="Fail if the output path is not up to date")
    registry_markdown_parser.add_argument("--json", action="store_true", help="Emit JSON")

    args = parser.parse_args(argv)
    root = args.root.resolve()

    if args.command == "list":
        return _cmd_list(root, json_output=args.json)
    if args.command == "catalog":
        return _cmd_catalog(root, json_output=args.json)
    if args.command == "validate":
        return _cmd_validate(root, scenario_paths=args.scenario, json_output=args.json)
    if args.command == "plan":
        return _cmd_plan(root, args)
    if args.command == "run":
        return _cmd_run(root, args)
    if args.command == "noisy-fixture":
        return _cmd_noisy_fixture(root, args)
    if args.command == "noisy-smoke":
        return _cmd_noisy_smoke(root, args)
    if args.command == "noisy-partial-failures":
        return _cmd_noisy_partial_failures(root, args)
    if args.command == "triple-preview":
        return _cmd_triple_preview(root, args)
    if args.command == "pair-preview":
        return _cmd_pair_preview(root, args)
    if args.command == "temporal-model":
        return _cmd_temporal_model(root, args)
    if args.command == "recovery-benchmark":
        return _cmd_recovery_benchmark(root, args)
    if args.command == "adversarial-combos":
        return _cmd_adversarial_combos(root, args)
    if args.command == "evidence-discipline-combos":
        return _cmd_evidence_discipline_combos(root, args)
    if args.command == "conflicting-signal-combos":
        return _cmd_conflicting_signal_combos(root, args)
    if args.command == "confidence-calibration":
        return _cmd_confidence_calibration(root, args)
    if args.command == "benchmark-runner":
        return _cmd_benchmark_runner(root, args)
    if args.command == "doctor":
        return _cmd_doctor(json_output=args.json)
    if args.command == "docs-check":
        return _cmd_docs_check(root, json_output=args.json)
    if args.command == "fixture-hygiene":
        return _cmd_fixture_hygiene(root, json_output=args.json)
    if args.command == "release-manifest":
        return _cmd_release_manifest(root, output=args.output, artifact_dir=args.artifact_dir, json_output=args.json)
    if args.command == "artifact-registry":
        return _cmd_artifact_registry(root, args)
    parser.error(f"unknown command: {args.command}")
    return 2


def _cmd_list(root: Path, *, json_output: bool) -> int:
    packages = [load_scenario_package(path) for path in list_scenario_packages(root)]
    rows = [
        {
            "name": package.name,
            "domain": package.domain,
            "path": str(package.path.relative_to(root)),
            "environment_archetype": package.spec.get("environment_archetype"),
            "variants": default_variant_selection(package),
        }
        for package in packages
    ]
    if json_output:
        print(json.dumps({"count": len(rows), "scenarios": rows}, indent=2, sort_keys=True))
    else:
        for row in rows:
            print(f"{row['name']}\t{row['environment_archetype']}\t{row['path']}")
        print(f"count={len(rows)}")
    return 0


def _cmd_catalog(root: Path, *, json_output: bool) -> int:
    report = build_catalog_report(root)
    if json_output:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(f"count={report['count']}")
        print("by_domain=" + _format_counts(report["by_domain"]))
        print("by_archetype=" + _format_counts(report["by_archetype"]))
        print("by_live_readiness=" + _format_counts(report["by_live_readiness"]))
        for domain, summary in report["domains"].items():
            print(
                f"domain={domain}\tcount={summary['count']}\t"
                f"live_readiness={_format_counts(summary['live_readiness'])}\t"
                f"archetypes={_format_counts(summary['archetypes'])}"
            )
    invalid = [row for row in report["scenarios"] if not row["valid"]]
    return 0 if not invalid else 1


def _cmd_validate(root: Path, *, scenario_paths: list[Path] | None, json_output: bool) -> int:
    paths = [path if path.is_absolute() else root / path for path in scenario_paths] if scenario_paths else list_scenario_packages(root)
    rows = []
    for path in paths:
        package = load_scenario_package(path)
        failures = validate_scenario_package(package)
        rows.append(
            {
                "name": package.name,
                "path": str(package.path.relative_to(root)),
                "valid": not failures,
                "failures": failures,
            }
        )
    failed = [row for row in rows if not row["valid"]]
    if json_output:
        print(json.dumps({"valid": not failed, "count": len(rows), "scenarios": rows}, indent=2, sort_keys=True))
    else:
        for row in rows:
            status = "ok" if row["valid"] else "invalid"
            print(f"{status}\t{row['path']}")
            for failure in row["failures"]:
                print(f"  - {failure}")
        print(f"valid={len(rows) - len(failed)} invalid={len(failed)}")
    return 0 if not failed else 1


def _cmd_plan(root: Path, args: argparse.Namespace) -> int:
    try:
        report = _build_compatibility_plan_report(root, args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_plan_report(report)
    return 0


def _build_compatibility_plan_report(root: Path, args: argparse.Namespace) -> dict[str, Any]:
    collection_mode = args.collection_mode or "real"
    explicit_sets = _resolve_explicit_plan_sets(root, args)
    explicit_reports = [
        combination_compatibility_report([load_scenario_package(path) for path in scenario_paths], mode=collection_mode)
        for scenario_paths in explicit_sets
    ]
    random_report = None
    if args.random_compatible_combinations is not None:
        random_report = _build_random_compatibility_plan_report(
            root,
            count=args.random_compatible_combinations,
            size=args.random_combination_size,
            archetypes=args.random_archetype,
            seed=args.random_seed,
            mode=collection_mode,
        )
    if not explicit_reports and random_report is None:
        raise ValueError("one of --scenario, --combination, or --random-compatible-combinations is required")
    return {
        "kind": "CombinationPlannerReport",
        "collection_mode": collection_mode,
        "explicit": {
            "count": len(explicit_reports),
            "included_count": sum(1 for report in explicit_reports if report["compatible"]),
            "rejected_count": sum(1 for report in explicit_reports if not report["compatible"]),
            "combinations": explicit_reports,
        },
        "random": random_report,
        "summary": _planner_summary(explicit_reports, random_report),
    }


def _resolve_explicit_plan_sets(root: Path, args: argparse.Namespace) -> list[list[Path]]:
    combination_sets: list[list[Path]] = []
    scenario_paths = [_resolve_cli_path(root, path) for path in args.scenario or []]
    if scenario_paths:
        if len(scenario_paths) == 1 and (args.combination or args.random_compatible_combinations):
            raise ValueError("--scenario must be repeated at least twice when combined with batch combination flags")
        combination_sets.append(scenario_paths)
    for value in args.combination or []:
        combination_sets.append(_parse_combination_set(root, value))
    return combination_sets


def _build_random_compatibility_plan_report(
    root: Path,
    *,
    count: int,
    size: int,
    archetypes: list[str] | None,
    seed: int | None,
    mode: str,
) -> dict[str, Any]:
    candidate_reports, groups = _random_compatibility_candidate_reports(root, size=size, archetypes=archetypes, mode=mode)
    compatible_reports = [report for report in candidate_reports if report["compatible"]]
    if count > len(compatible_reports):
        raise ValueError(f"requested {count} random combinations, but only {len(compatible_reports)} compatible combinations exist")
    selected_keys = _select_random_report_keys(compatible_reports, count=count, seed=seed)
    for report in candidate_reports:
        report["selected"] = _report_path_key(report) in selected_keys
    selected_reports = [report for report in candidate_reports if _report_path_key(report) in selected_keys]
    rejected_reports = [report for report in candidate_reports if not report["compatible"]]
    return {
        "requested": count,
        "combination_size": size,
        "archetypes": list(archetypes or []),
        "seed": seed,
        "compatibility_mode": mode,
        "deterministic": seed is not None,
        "selected_count": len(selected_reports),
        "eligible_count": sum(1 for report in candidate_reports if report["compatible"]),
        "rejected_count": len(rejected_reports),
        "groups": groups,
        "selected": selected_reports,
        "candidate_pool": {
            "count": len(candidate_reports),
            "included_count": sum(1 for report in candidate_reports if report["compatible"]),
            "rejected_count": len(rejected_reports),
            "combination_size": size,
            "compatibility_mode": mode,
            "reason_counts": _reason_counts(candidate_reports),
        },
        "rejected": rejected_reports,
    }


def _random_compatibility_candidate_reports(
    root: Path,
    *,
    size: int,
    archetypes: list[str] | None,
    mode: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if size < 2:
        raise ValueError("--random-combination-size must be at least 2")
    requested_archetypes = {archetype for archetype in archetypes or [] if archetype}
    packages = [load_scenario_package(path) for path in list_scenario_packages(root)]
    package_groups: dict[str, list[Any]] = defaultdict(list)
    available_archetypes: set[str] = set()
    for package in packages:
        axes = package.spec.get("variant_axes", {})
        collection_modes = axes.get("collection_mode", []) if isinstance(axes, dict) else []
        if mode not in collection_modes:
            continue
        archetype = str(package.spec.get("environment_archetype") or "")
        if requested_archetypes and archetype not in requested_archetypes:
            continue
        if archetype:
            available_archetypes.add(archetype)
        group_key = archetype if mode == "real" else "fixture"
        if group_key:
            package_groups[group_key].append(package)
    missing_archetypes = sorted(requested_archetypes - available_archetypes)
    if missing_archetypes:
        raise ValueError(f"no {mode}-compatible scenarios found for archetype(s): {', '.join(missing_archetypes)}")
    reports: list[dict[str, Any]] = []
    groups: list[dict[str, Any]] = []
    for archetype, archetype_packages in sorted(package_groups.items()):
        sorted_packages = sorted(archetype_packages, key=lambda package: package.name)
        if len(sorted_packages) < size:
            continue
        candidate_count = comb(len(sorted_packages), size)
        if candidate_count > MAX_ENUMERATED_RANDOM_COMBINATIONS:
            raise ValueError(
                "planner report would enumerate "
                f"{candidate_count} combinations for archetype {archetype}; use a smaller --random-combination-size"
            )
        group_reports = [
            combination_compatibility_report(list(candidate), mode=mode)
            for candidate in itertools.combinations(sorted_packages, size)
        ]
        for report in group_reports:
            report["archetype"] = archetype
        reports.extend(group_reports)
        groups.append(
            {
                "archetype": archetype,
                "scenario_count": len(sorted_packages),
                "candidate_count": len(group_reports),
                "included_count": sum(1 for report in group_reports if report["compatible"]),
                "rejected_count": sum(1 for report in group_reports if not report["compatible"]),
            }
        )
    if not reports:
        raise ValueError(f"no compatible scenario groups can satisfy --random-combination-size {size}")
    return reports, groups


def _select_random_report_keys(reports: list[dict[str, Any]], *, count: int, seed: int | None) -> set[tuple[str, ...]]:
    if count <= 0:
        raise ValueError("--random-compatible-combinations must be positive")
    ordered_reports = sorted(reports, key=_report_path_key)
    rng = random.Random(seed) if seed is not None else random.SystemRandom()
    selected = rng.sample(ordered_reports, count)
    return {_report_path_key(report) for report in selected}


def _planner_summary(explicit_reports: list[dict[str, Any]], random_report: dict[str, Any] | None) -> dict[str, Any]:
    reason_counts = Counter(_reason_counts(explicit_reports))
    candidate_count = len(explicit_reports)
    included_count = sum(1 for report in explicit_reports if report["compatible"])
    rejected_count = sum(1 for report in explicit_reports if not report["compatible"])
    selected_count = 0
    if random_report is not None:
        candidate_pool = random_report["candidate_pool"]
        candidate_count += candidate_pool["count"]
        included_count += candidate_pool["included_count"]
        rejected_count += candidate_pool["rejected_count"]
        selected_count = random_report["selected_count"]
        reason_counts.update(candidate_pool.get("reason_counts", {}))
    return {
        "candidate_count": candidate_count,
        "included_count": included_count,
        "rejected_count": rejected_count,
        "selected_count": selected_count,
        "reason_counts": dict(sorted(reason_counts.items())),
    }


def _reason_counts(reports: list[dict[str, Any]]) -> dict[str, int]:
    reason_counts: Counter[str] = Counter()
    for report in reports:
        for reason in report.get("reason_details", []):
            code = str(reason.get("code") or "unknown")
            reason_counts[code] += 1
    return dict(sorted(reason_counts.items()))


def _combination_path_key(paths: list[Path]) -> tuple[str, ...]:
    return tuple(sorted(str(path.resolve()) for path in paths))


def _report_path_key(report: dict[str, Any]) -> tuple[str, ...]:
    return tuple(sorted(str(path) for path in report.get("scenario_paths", [])))


def _cmd_run(root: Path, args: argparse.Namespace) -> int:
    try:
        variants = parse_variant_args(args.variants)
        combination_sets, source = _resolve_combination_sets(root, args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    collection_mode = args.collection_mode
    if collection_mode is None and (args.combination or args.random_compatible_combinations):
        collection_mode = "real"
    if collection_mode is None and args.warm_kind:
        collection_mode = "real"
    hold_seconds = None
    if args.hold:
        hold_seconds = -1.0
    if args.hold_seconds is not None:
        hold_seconds = args.hold_seconds
    try:
        if args.warm_kind:
            _validate_warm_kind_request(root, combination_sets, source=source, collection_mode=collection_mode)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    progress_reporter = _build_progress_reporter(root, args)
    try:
        if _is_batch_run(combination_sets, source):
            result = _run_combination_batch(
                root,
                args,
                combination_sets,
                variants=variants,
                collection_mode=collection_mode,
                hold_seconds=hold_seconds,
                progress_reporter=progress_reporter,
                source=source,
            )
        else:
            result = _run_one_combination(
                root,
                args,
                combination_sets[0],
                variants=variants,
                collection_mode=collection_mode,
                hold_seconds=hold_seconds,
                progress_reporter=progress_reporter,
            )
    finally:
        if progress_reporter is not None:
            progress_reporter.close()
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        _print_run_result(result)
    return 1 if result.get("blocked") else 0


def _cmd_noisy_fixture(root: Path, args: argparse.Namespace) -> int:
    package = load_scenario_package(_resolve_cli_path(root, args.scenario))
    payload = render_noisy_fixture_bundle(
        root,
        package,
        seed=args.seed,
        max_noise_sources=args.max_noise_sources,
    )
    if args.output is not None:
        output = args.output if args.output.is_absolute() else root / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json or args.output is None:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"noisy_fixture_manifest={args.output}")
        print(f"artifact_hash={payload['artifact_hash']}")
        print(f"noise_sources={len(payload['noise_profile']['source_ids'])}")
    return 0


def _cmd_noisy_smoke(root: Path, args: argparse.Namespace) -> int:
    payload = render_noisy_smoke_report(
        root,
        smoke_path=args.smoke,
        seed=args.seed,
        max_noise_sources=args.max_noise_sources,
    )
    if args.output is not None:
        output = args.output if args.output.is_absolute() else root / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json or args.output is None:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"noisy_smoke_report={args.output}")
        print(f"artifact_hash={payload['artifact_hash']}")
        print(f"passed={payload['passed']}")
        print(f"scenario_count={payload['scenario_count']}")
    return 0 if payload.get("passed") else 1


def _cmd_noisy_partial_failures(root: Path, args: argparse.Namespace) -> int:
    payload = render_noisy_partial_failure_pack(
        root,
        pack_path=args.pack,
        seed=args.seed,
        max_noise_sources=args.max_noise_sources,
    )
    if args.output is not None:
        output = args.output if args.output.is_absolute() else root / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json or args.output is None:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"noisy_partial_failure_pack_report={args.output}")
        print(f"artifact_hash={payload['artifact_hash']}")
        print(f"passed={payload['passed']}")
        print(f"variant_count={payload['variant_count']}")
    return 0 if payload.get("passed") else 1


def _cmd_triple_preview(root: Path, args: argparse.Namespace) -> int:
    payload = render_triple_benchmark_fixture_preview(
        root,
        preview_path=args.preview,
        seed=args.seed,
        selected_count=args.selected_count,
    )
    if args.output is not None:
        output = args.output if args.output.is_absolute() else root / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json or args.output is None:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"triple_preview_report={args.output}")
        print(f"artifact_hash={payload['artifact_hash']}")
        print(f"passed={payload['passed']}")
        print(f"selected_count={payload['selected_count']}")
    return 0 if payload.get("passed") else 1


def _cmd_pair_preview(root: Path, args: argparse.Namespace) -> int:
    payload = render_random_pair_fixture_preview(
        root,
        preview_path=args.preview,
        seed=args.seed,
        selected_count=args.selected_count,
    )
    if args.output is not None:
        output = args.output if args.output.is_absolute() else root / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json or args.output is None:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"pair_preview_report={args.output}")
        print(f"artifact_hash={payload['artifact_hash']}")
        print(f"passed={payload['passed']}")
        print(f"selected_count={payload['selected_count']}")
    return 0 if payload.get("passed") else 1


def _cmd_temporal_model(root: Path, args: argparse.Namespace) -> int:
    payload = render_temporal_benchmark_model(root, model_path=args.model)
    if args.output is not None:
        output = args.output if args.output.is_absolute() else root / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json or args.output is None:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"temporal_model_report={args.output}")
        print(f"artifact_hash={payload['artifact_hash']}")
        print(f"passed={payload['passed']}")
        print(f"phase_count={payload['phase_count']}")
    return 0 if payload.get("passed") else 1


def _cmd_recovery_benchmark(root: Path, args: argparse.Namespace) -> int:
    payload = render_recovery_after_diagnosis_benchmark(root, benchmark_path=args.benchmark)
    if args.output is not None:
        output = args.output if args.output.is_absolute() else root / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json or args.output is None:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"recovery_benchmark_report={args.output}")
        print(f"artifact_hash={payload['artifact_hash']}")
        print(f"passed={payload['passed']}")
        print(f"case_count={payload['case_count']}")
    return 0 if payload.get("passed") else 1


def _cmd_adversarial_combos(root: Path, args: argparse.Namespace) -> int:
    payload = render_adversarial_combo_report(root, combo_path=args.combos)
    if args.output is not None:
        output = args.output if args.output.is_absolute() else root / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json or args.output is None:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"adversarial_combo_report={args.output}")
        print(f"artifact_hash={payload['artifact_hash']}")
        print(f"passed={payload['passed']}")
        print(f"combo_count={payload['combo_count']}")
    return 0 if payload.get("passed") else 1


def _cmd_evidence_discipline_combos(root: Path, args: argparse.Namespace) -> int:
    payload = render_evidence_discipline_combo_report(root, combo_path=args.combos)
    if args.output is not None:
        output = args.output if args.output.is_absolute() else root / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json or args.output is None:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"evidence_discipline_combo_report={args.output}")
        print(f"artifact_hash={payload['artifact_hash']}")
        print(f"passed={payload['passed']}")
        print(f"combo_count={payload['combo_count']}")
    return 0 if payload.get("passed") else 1


def _cmd_conflicting_signal_combos(root: Path, args: argparse.Namespace) -> int:
    payload = render_conflicting_signal_combo_report(root, combo_path=args.combos)
    if args.output is not None:
        output = args.output if args.output.is_absolute() else root / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json or args.output is None:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"conflicting_signal_combo_report={args.output}")
        print(f"artifact_hash={payload['artifact_hash']}")
        print(f"passed={payload['passed']}")
        print(f"combo_count={payload['combo_count']}")
    return 0 if payload.get("passed") else 1


def _cmd_confidence_calibration(root: Path, args: argparse.Namespace) -> int:
    payload = render_confidence_calibration_report(root, calibration_path=args.calibration)
    if args.output is not None:
        output = args.output if args.output.is_absolute() else root / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json or args.output is None:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"confidence_calibration_report={args.output}")
        print(f"artifact_hash={payload['artifact_hash']}")
        print(f"passed={payload['passed']}")
        print(f"case_count={payload['case_count']}")
    return 0 if payload.get("passed") else 1


def _cmd_benchmark_runner(root: Path, args: argparse.Namespace) -> int:
    try:
        payload = run_agent_adapter_benchmark(
            root,
            exchange_path=args.exchange,
            adapter_command=args.adapter_command,
            expected_hypotheses=args.expected_hypothesis,
            forbidden_hypotheses=args.forbidden_hypothesis,
            false_attribution_guards=args.false_attribution_guard,
            evidence_role_expectations=parse_evidence_role_expectations(args.evidence_role),
            required_abstention=args.required_abstention,
            uncertainty_expected=args.uncertainty_expected,
            scenario_ids=args.scenario_id,
            archetype=args.archetype,
            result_id=args.result_id,
            created_at=args.created_at,
        )
    except (BenchmarkRunnerError, OSError, json.JSONDecodeError) as exc:
        print(f"benchmark-runner error: {exc}", file=sys.stderr)
        return 2
    if args.output is not None:
        output = args.output if args.output.is_absolute() else root / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if args.json or args.output is None:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        aggregate = payload["aggregate"]
        result = payload["results"][0]
        print(
            f"benchmark_runner_result={args.output}\tcase={result['case_id']}\t"
            f"entrant={result['entrant_id']}\tstate={result['state']}"
        )
        print(
            f"result_count={aggregate['result_count']}\tpassed={aggregate['passed_count']}\t"
            f"failed={aggregate['failed_count']}\tblocked={aggregate['blocked_count']}"
        )
    bad_result = any(result.get("state") in {"failed", "blocked", "error"} for result in payload["results"])
    return 0 if not bad_result else 1


def _build_progress_reporter(root: Path, args: argparse.Namespace) -> OperatorProgressReporter | None:
    if not (args.progress or args.progress_json or args.progress_artifact_dir):
        return None
    stream_format = "ndjson" if args.progress_json else "human" if args.progress else None
    artifact_dir = args.progress_artifact_dir
    if artifact_dir is None:
        artifact_dir = default_artifact_dir(root, args.incident_session_id)
    elif not artifact_dir.is_absolute():
        artifact_dir = root / artifact_dir
    return OperatorProgressReporter(stream=sys.stderr, stream_format=stream_format, artifact_dir=artifact_dir)


def _resolve_combination_sets(root: Path, args: argparse.Namespace) -> tuple[list[list[Path]], dict[str, Any]]:
    combination_sets: list[list[Path]] = []
    source = {
        "specified": 0,
        "random": 0,
        "random_combination_size": args.random_combination_size,
        "random_archetypes": list(args.random_archetype or []),
        "random_seed": args.random_seed,
    }
    scenario_paths = [_resolve_cli_path(root, path) for path in args.scenario or []]
    if scenario_paths:
        if len(scenario_paths) == 1 and (args.combination or args.random_compatible_combinations):
            raise ValueError("--scenario must be repeated at least twice when combined with batch combination flags")
        combination_sets.append(scenario_paths)
        source["specified"] += 1
    for value in args.combination or []:
        combination_sets.append(_parse_combination_set(root, value))
        source["specified"] += 1
    if args.random_compatible_combinations is not None:
        random_sets = _random_compatible_combination_sets(
            root,
            count=args.random_compatible_combinations,
            size=args.random_combination_size,
            archetypes=args.random_archetype,
            seed=args.random_seed,
        )
        combination_sets.extend(random_sets)
        source["random"] = len(random_sets)
    if not combination_sets:
        raise ValueError("one of --scenario, --combination, or --random-compatible-combinations is required")
    return combination_sets, source


def _parse_combination_set(root: Path, value: str) -> list[Path]:
    raw_paths = [part.strip() for part in value.split(",") if part.strip()]
    if len(raw_paths) < 2:
        raise ValueError(f"--combination requires at least two comma-separated scenario paths: {value}")
    return [_resolve_cli_path(root, Path(raw_path)) for raw_path in raw_paths]


def _random_compatible_combination_sets(
    root: Path,
    *,
    count: int,
    size: int,
    archetypes: list[str] | None = None,
    seed: int | None = None,
) -> list[list[Path]]:
    if count <= 0:
        raise ValueError("--random-compatible-combinations must be positive")
    if size < 2:
        raise ValueError("--random-combination-size must be at least 2")
    try:
        candidate_reports, _groups = _random_compatibility_candidate_reports(
            root,
            size=size,
            archetypes=archetypes,
            mode="real",
        )
    except ValueError as exc:
        if "planner report would enumerate" not in str(exc):
            raise
    else:
        compatible_reports = [report for report in candidate_reports if report["compatible"]]
        if count > len(compatible_reports):
            raise ValueError(
                f"requested {count} random combinations, but only {len(compatible_reports)} compatible combinations exist"
            )
        selected_keys = _select_random_report_keys(compatible_reports, count=count, seed=seed)
        return [
            [_resolve_cli_path(root, Path(str(path))) for path in report.get("scenario_paths", [])]
            for report in candidate_reports
            if _report_path_key(report) in selected_keys
        ]
    requested_archetypes = {archetype for archetype in archetypes or [] if archetype}
    packages = [load_scenario_package(path) for path in list_scenario_packages(root)]
    groups: dict[str, list[Any]] = defaultdict(list)
    for package in packages:
        axes = package.spec.get("variant_axes", {})
        collection_modes = axes.get("collection_mode", []) if isinstance(axes, dict) else []
        if "real" not in collection_modes:
            continue
        archetype = str(package.spec.get("environment_archetype") or "")
        if requested_archetypes and archetype not in requested_archetypes:
            continue
        if archetype:
            groups[archetype].append(package)
    missing_archetypes = sorted(requested_archetypes - set(groups))
    if missing_archetypes:
        raise ValueError(f"no real-compatible scenarios found for archetype(s): {', '.join(missing_archetypes)}")
    eligible: list[tuple[str, list[Any], int, list[tuple[Any, ...]] | None]] = []
    for archetype, archetype_packages in sorted(groups.items()):
        sorted_packages = sorted(archetype_packages, key=lambda package: package.name)
        group_count = comb(len(sorted_packages), size)
        if len(sorted_packages) < size:
            continue
        if group_count <= MAX_ENUMERATED_RANDOM_COMBINATIONS:
            combinations = [
                tuple(candidate)
                for candidate in itertools.combinations(sorted_packages, size)
                if scenarios_are_compatible_for_mode(list(candidate), mode="real")
            ]
            group_count = len(combinations)
            if group_count:
                eligible.append((archetype, sorted_packages, group_count, combinations))
            continue
        eligible.append((archetype, sorted_packages, group_count, None))
    total = sum(group_count for *_group, group_count, _combinations in eligible)
    if not eligible:
        raise ValueError(f"no compatible scenario groups can satisfy --random-combination-size {size}")
    if count > total:
        raise ValueError(f"requested {count} random combinations, but only {total} compatible combinations exist")

    rng = random.Random(seed) if seed is not None else random.SystemRandom()
    selected: list[list[Path]] = []
    seen: set[tuple[str, ...]] = set()
    attempts = 0
    max_attempts = max(100, count * 50)
    while len(selected) < count and attempts < max_attempts:
        attempts += 1
        _archetype, archetype_packages, precomputed = _weighted_random_group(eligible, rng)
        if precomputed is not None:
            sampled = list(rng.choice(precomputed))
        else:
            sampled = sorted(rng.sample(archetype_packages, size), key=lambda package: package.name)
            if not scenarios_are_compatible_for_mode(sampled, mode="real"):
                continue
        key = tuple(str(package.path.resolve()) for package in sampled)
        if key in seen:
            continue
        seen.add(key)
        selected.append([package.path for package in sampled])
    if len(selected) < count:
        raise ValueError("could not sample enough unique compatible combinations; try a smaller count")
    return selected


def _weighted_random_group(
    groups: list[tuple[str, list[Any], int, list[tuple[Any, ...]] | None]],
    rng: random.Random,
) -> tuple[str, list[Any], list[tuple[Any, ...]] | None]:
    target = rng.randrange(sum(group_count for *_group, group_count, _combinations in groups))
    cursor = 0
    for archetype, packages, group_count, combinations in groups:
        cursor += group_count
        if target < cursor:
            return archetype, packages, combinations
    archetype, packages, _group_count, combinations = groups[-1]
    return archetype, packages, combinations


def _resolve_cli_path(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _is_batch_run(combination_sets: list[list[Path]], source: dict[str, Any]) -> bool:
    return len(combination_sets) > 1 or bool(source.get("random")) or bool(source.get("specified") and source["specified"] > 1)


def _validate_warm_kind_request(
    root: Path,
    combination_sets: list[list[Path]],
    *,
    source: dict[str, Any],
    collection_mode: str | None,
) -> None:
    if not _is_batch_run(combination_sets, source):
        raise ValueError("--warm-kind requires a combinatorial batch with at least two runs")
    if collection_mode != "real":
        raise ValueError("--warm-kind requires real collection mode")
    packages = [load_scenario_package(path) for scenario_paths in combination_sets for path in scenario_paths]
    non_kind = sorted(
        str(package.path.relative_to(root))
        for package in packages
        if str(package.spec.get("environment_archetype") or "") != "kind"
    )
    if non_kind:
        raise ValueError("--warm-kind only supports kind scenarios; non-kind scenario(s): " + ", ".join(non_kind))


def _run_combination_batch(
    root: Path,
    args: argparse.Namespace,
    combination_sets: list[list[Path]],
    *,
    variants: dict[str, str],
    collection_mode: str | None,
    hold_seconds: float | None,
    progress_reporter: OperatorProgressReporter | None,
    source: dict[str, Any],
) -> dict[str, Any]:
    warm_kind = bool(getattr(args, "warm_kind", False))
    original_env: dict[str, str | None] = {}
    if warm_kind:
        original_env = _set_temporary_env(WARM_KIND_ENV)
    warm_kind_cleanup = None
    try:
        try:
            runs = [
                _run_one_combination(
                    root,
                    args,
                    scenario_paths,
                    variants=variants,
                    collection_mode=collection_mode,
                    hold_seconds=hold_seconds,
                    progress_reporter=progress_reporter,
                    batch_index=index,
                )
                for index, scenario_paths in enumerate(combination_sets, start=1)
            ]
        finally:
            if warm_kind:
                _restore_temporary_env(original_env)
    finally:
        if warm_kind:
            warm_kind_cleanup = _cleanup_warm_kind(root, progress_reporter=progress_reporter)
    blocked = [run for run in runs if run.get("blocked")]
    cleanup_blocked = bool(warm_kind_cleanup and not warm_kind_cleanup.get("verified"))
    result = {
        "kind": "IncidentRunBatch",
        "batch": True,
        "count": len(runs),
        "generated": not blocked and not cleanup_blocked,
        "blocked": bool(blocked) or cleanup_blocked,
        "generated_count": len(runs) - len(blocked),
        "blocked_count": len(blocked),
        "collection_mode": collection_mode or "fixture",
        "combination_source": source,
        "runs": runs,
    }
    if warm_kind_cleanup is not None:
        result["warm_kind"] = {
            "enabled": True,
            "env": sorted(WARM_KIND_ENV),
            "cleanup": warm_kind_cleanup,
        }
        if cleanup_blocked:
            result["blocking_reasons"] = _failure_reasons(warm_kind_cleanup.get("failures", []))
    apply_failure_classification(result)
    if progress_reporter is not None:
        progress_reporter.emit(
            "batch",
            "blocked" if result["blocked"] else "ok",
            "combinatorial batch blocked" if result["blocked"] else "combinatorial batch complete",
            details={
                "count": len(runs),
                "blocked": bool(result["blocked"]),
                "warm_kind": warm_kind,
                "failure_class": result.get("failure_class"),
            },
        )
        progress_reporter.write_summary(result)
    return result


def _set_temporary_env(overrides: dict[str, str]) -> dict[str, str | None]:
    original = {key: os.environ.get(key) for key in overrides}
    os.environ.update(overrides)
    return original


def _restore_temporary_env(original: dict[str, str | None]) -> None:
    for key, value in original.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


def _cleanup_warm_kind(root: Path, *, progress_reporter: OperatorProgressReporter | None) -> dict[str, Any]:
    progress = progress_reporter
    if progress is not None:
        progress.emit("warm_kind_cleanup", "started", "deleting retained kind cluster")
    env = os.environ.copy()
    env["SRE_AGENT_KIND_KEEP_CLUSTER"] = "0"
    script = root / "harness/archetypes/kind/down.sh"
    completed = subprocess.run([str(script)], cwd=root, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    failures: list[dict[str, str]] = []
    if completed.returncode != 0:
        failures.append({"check": "kind_final_cleanup", "error": _completed_error(completed, "kind cleanup failed")})
    cluster_name = env.get("SRE_AGENT_KIND_CLUSTER", "sre-agent-phase-a")
    clusters = subprocess.run(["kind", "get", "clusters"], cwd=root, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if clusters.returncode == 0 and cluster_name in _split_lines(clusters.stdout):
        failures.append({"check": "kind_cluster_deleted", "error": f"kind cluster still exists: {cluster_name}"})
    elif clusters.returncode != 0:
        failures.append({"check": "kind_cluster_verifier", "error": _completed_error(clusters, "could not verify kind cleanup")})
    if progress is not None:
        progress.emit(
            "warm_kind_cleanup",
            "ok" if not failures else "failed",
            "retained kind cluster deleted" if not failures else "retained kind cleanup failed",
            details={"failures": failures},
        )
    try:
        command_path = str(script.relative_to(root))
    except ValueError:
        command_path = str(script)
    return {
        "verified": not failures,
        "failures": failures,
        "cluster": cluster_name,
        "command": command_path,
    }


def _completed_error(completed: subprocess.CompletedProcess[str], fallback: str) -> str:
    text = (completed.stderr or completed.stdout or fallback).strip() or fallback
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return (lines[-1] if lines else fallback)[:500]


def _split_lines(value: str) -> set[str]:
    return {line.strip() for line in value.splitlines() if line.strip()}


def _failure_reasons(failures: list[dict[str, Any]]) -> list[str]:
    return [f"{failure.get('check', 'check')}: {failure.get('error', 'failed')}" for failure in failures]


def _run_one_combination(
    root: Path,
    args: argparse.Namespace,
    scenario_paths: list[Path],
    *,
    variants: dict[str, str],
    collection_mode: str | None,
    hold_seconds: float | None,
    progress_reporter: OperatorProgressReporter | None,
    batch_index: int | None = None,
) -> dict[str, Any]:
    incident_session_id = args.incident_session_id
    if batch_index is not None:
        incident_session_id = f"{incident_session_id}-{batch_index}"
    if len(scenario_paths) == 1:
        return stand_up_incident_environment(
            load_scenario_package(scenario_paths[0]),
            variants=variants,
            collection_mode=collection_mode,
            incident_id=args.incident_id,
            incident_session_id=incident_session_id,
            require_tools=args.require_tools,
            workdir=root,
            hold_seconds=hold_seconds,
            progress_reporter=progress_reporter,
        )
    return stand_up_combinatorial_incident_environment(
        [load_scenario_package(path) for path in scenario_paths],
        variants=variants,
        collection_mode=collection_mode,
        incident_id=args.incident_id,
        incident_session_id=incident_session_id,
        require_tools=args.require_tools,
        workdir=root,
        hold_seconds=hold_seconds,
        progress_reporter=progress_reporter,
    )


def _cmd_doctor(*, json_output: bool) -> int:
    import shutil

    tools = {name: bool(shutil.which(name)) for name in ("docker", "kind", "kubectl", "helm", "curl")}
    if json_output:
        print(json.dumps({"tools": tools}, indent=2, sort_keys=True))
    else:
        for name, present in tools.items():
            print(f"{'ok' if present else 'missing'}\t{name}")
    return 0


def _cmd_docs_check(root: Path, *, json_output: bool) -> int:
    payload = findings_payload(check_markdown_links(root))
    _print_check_payload(payload, json_output=json_output, ok_label="docs-check ok")
    return 0 if payload["ok"] else 1


def _cmd_fixture_hygiene(root: Path, *, json_output: bool) -> int:
    payload = findings_payload(check_fixture_hygiene(root))
    _print_check_payload(payload, json_output=json_output, ok_label="fixture-hygiene ok")
    return 0 if payload["ok"] else 1


def _cmd_release_manifest(root: Path, *, output: Path, artifact_dir: Path, json_output: bool) -> int:
    resolved_output = output if output.is_absolute() else root / output
    resolved_artifact_dir = artifact_dir if artifact_dir.is_absolute() else root / artifact_dir
    manifest = write_release_manifest(root, resolved_output, artifact_dir=resolved_artifact_dir)
    if json_output:
        print(json.dumps(manifest, indent=2, sort_keys=True))
    else:
        print(f"release_manifest={resolved_output}")
        print(f"scenario_catalog_hash={manifest['scenario_catalog']['hash']}")
        print(f"benchmark_sets={len(manifest['benchmark_release']['benchmark_sets'])}")
        print(f"scenario_hashes={len(manifest['benchmark_release']['scenario_hashes'])}")
        print(f"artifacts={len(manifest['artifacts'])}")
    return 0


def _cmd_artifact_registry(root: Path, args: argparse.Namespace) -> int:
    if args.registry_command == "add":
        return _cmd_artifact_registry_add(root, args)
    if args.registry_command == "check":
        return _cmd_artifact_registry_check(root, args)
    if args.registry_command == "markdown":
        return _cmd_artifact_registry_markdown(root, args)
    raise ValueError(f"unsupported artifact registry command: {args.registry_command}")


def _cmd_artifact_registry_add(root: Path, args: argparse.Namespace) -> int:
    try:
        env = parse_env_assignments(args.env)
        registry = append_registry_entry(
            root,
            registry_path=args.registry,
            artifact_dir=args.artifact_dir,
            benchmark_set_id=args.benchmark_set_id,
            command=args.benchmark_command,
            run_id=args.run_id,
            seed=args.seed,
            env=env,
            host_profile=args.host_profile,
            docker_host_kind=args.docker_host_kind,
            docker_host=args.docker_host,
            architecture=args.architecture,
            cpu_count=args.cpu_count,
            memory_bytes=args.memory_bytes,
            docker_data_root_free_bytes=args.docker_data_root_free_bytes,
            agent_replay_summary=args.agent_replay_summary,
            created_at=args.created_at,
        )
    except ArtifactRegistryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    entry = registry["entries"][-1]
    if args.json:
        print(
            json.dumps(
                {
                    "ok": True,
                    "registry": str(args.registry),
                    "entry_count": len(registry["entries"]),
                    "entry": entry,
                },
                indent=2,
                sort_keys=True,
            )
        )
    else:
        print(f"registry={args.registry}")
        print(f"entry_count={len(registry['entries'])}")
        print(f"run_id={entry['run_id']}")
        print(f"state={entry['state']}")
        print(f"failure_class={entry['failure_class']}")
    return 0


def _cmd_artifact_registry_check(root: Path, args: argparse.Namespace) -> int:
    payload = registry_check_payload(root, registry_path=args.registry)
    _print_check_payload(payload, json_output=args.json, ok_label="artifact-registry check ok")
    return 0 if payload["ok"] else 1


def _cmd_artifact_registry_markdown(root: Path, args: argparse.Namespace) -> int:
    if args.check_output is not None:
        payload = registry_markdown_check_payload(root, registry_path=args.registry, output=args.check_output)
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        elif payload["ok"]:
            print(f"artifact-registry markdown ok\toutput={payload['output']}")
        else:
            print(f"artifact-registry markdown drift\toutput={payload['output']}")
        return 0 if payload["ok"] else 1
    if args.output is not None:
        write_registry_markdown(root, registry_path=args.registry, output=args.output)
        payload = {"ok": True, "output": str(args.output)}
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            print(f"artifact_registry_markdown={args.output}")
        return 0
    markdown = render_registry_markdown(root, registry_path=args.registry)
    if args.json:
        print(json.dumps({"ok": True, "markdown": markdown}, indent=2, sort_keys=True))
    else:
        print(markdown, end="")
    return 0


def _print_run_result(result: dict[str, Any]) -> None:
    if result.get("batch"):
        status = "blocked" if result.get("blocked") else "generated"
        print(f"{status}\tbatch\t{result.get('collection_mode')}")
        print(
            f"runs={result.get('count')}\tgenerated={result.get('generated_count')}\t"
            f"blocked={result.get('blocked_count')}"
        )
        print(f"failure_class={result.get('failure_class', 'none')}")
        for index, run in enumerate(result.get("runs", []), start=1):
            run_status = "blocked" if run.get("blocked") else "generated"
            print(
                f"run[{index}]={run_status}\t{run.get('scenario')}\t{run.get('collection_mode')}\t"
                f"failure_class={run.get('failure_class', 'none')}"
            )
            for failure in run.get("blocking_reasons", []):
                print(f"run[{index}].blocking_reason={failure}")
        return
    status = "blocked" if result.get("blocked") else "generated"
    print(f"{status}\t{result.get('scenario')}\t{result.get('collection_mode')}")
    if result.get("combined"):
        print(f"scenario_count={result.get('scenario_count')}")
        for scenario in result.get("scenarios", []):
            if isinstance(scenario, dict):
                print(
                    f"component={scenario.get('name')}\t"
                    f"{scenario.get('environment_archetype')}\t{scenario.get('path')}"
                )
    for key in ("incident_id", "environment_archetype", "fixture"):
        if result.get(key):
            print(f"{key}={result[key]}")
    print(f"failure_class={result.get('failure_class', 'none')}")
    for fixture in result.get("fixtures", []):
        print(f"fixture={fixture}")
    for failure in result.get("blocking_reasons", []):
        print(f"blocking_reason={failure}")


def _print_plan_report(report: dict[str, Any]) -> None:
    summary = report["summary"]
    print(
        f"plan\tcollection_mode={report['collection_mode']}\t"
        f"candidates={summary['candidate_count']}\tincluded={summary['included_count']}\t"
        f"rejected={summary['rejected_count']}\tselected={summary['selected_count']}"
    )
    explicit = report.get("explicit", {})
    if explicit.get("count"):
        print(
            f"explicit\tcount={explicit['count']}\t"
            f"included={explicit['included_count']}\trejected={explicit['rejected_count']}"
        )
        for index, item in enumerate(explicit.get("combinations", []), start=1):
            _print_plan_item(f"explicit[{index}]", item)
    random_report = report.get("random")
    if random_report:
        print(
            f"random\trequested={random_report['requested']}\tsize={random_report['combination_size']}\t"
            f"eligible={random_report['eligible_count']}\trejected={random_report['rejected_count']}"
        )
        for group in random_report.get("groups", []):
            print(
                f"random.group\t{group['archetype']}\tscenarios={group['scenario_count']}\t"
                f"candidates={group['candidate_count']}\tincluded={group['included_count']}\t"
                f"rejected={group['rejected_count']}"
            )
        for index, item in enumerate(random_report.get("selected", []), start=1):
            _print_plan_item(f"selected[{index}]", item)
        rejected = random_report.get("rejected", [])
        for index, item in enumerate(rejected[:20], start=1):
            _print_plan_item(f"rejected[{index}]", item)
        if len(rejected) > 20:
            print(f"rejected_remaining={len(rejected) - 20}")


def _print_plan_item(label: str, item: dict[str, Any]) -> None:
    print(f"{label}\t{item['decision']}\t{'+'.join(item.get('scenario_names', []))}")
    for reason in item.get("reasons", []):
        print(f"{label}.reason={reason}")


def _format_counts(counts: dict[str, int]) -> str:
    return ",".join(f"{key}:{value}" for key, value in sorted(counts.items()))


def _print_check_payload(payload: dict[str, Any], *, json_output: bool, ok_label: str) -> None:
    if json_output:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    if payload["ok"]:
        print(f"{ok_label}\twarnings={payload['warning_count']}")
        return
    for finding in payload["findings"]:
        location = finding["path"]
        if "line" in finding:
            location = f"{location}:{finding['line']}"
        print(f"{finding['severity']}\t{finding['rule']}\t{location}\t{finding['message']}")
