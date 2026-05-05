"""Command line interface for the incident generator."""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from math import comb
from pathlib import Path
from typing import Any

from .checks import check_fixture_hygiene, check_markdown_links, findings_payload
from .progress import OperatorProgressReporter, default_artifact_dir
from .release import write_release_manifest
from .scenarios import (
    COLLECTION_MODES,
    build_catalog_report,
    default_variant_selection,
    list_scenario_packages,
    load_scenario_package,
    parse_variant_args,
    stand_up_combinatorial_incident_environment,
    stand_up_incident_environment,
    validate_scenario_package,
)


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
    run_parser.add_argument("--variant", action="append", dest="variants", help="Variant override as axis=value")
    run_parser.add_argument("--collection-mode", choices=sorted(COLLECTION_MODES))
    run_parser.add_argument("--incident-id")
    run_parser.add_argument("--incident-session-id", default="incident-generator-run")
    run_parser.add_argument("--require-tools", action="store_true", help="Do not fall back to fixture mode if real tools are absent")
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

    args = parser.parse_args(argv)
    root = args.root.resolve()

    if args.command == "list":
        return _cmd_list(root, json_output=args.json)
    if args.command == "catalog":
        return _cmd_catalog(root, json_output=args.json)
    if args.command == "validate":
        return _cmd_validate(root, scenario_paths=args.scenario, json_output=args.json)
    if args.command == "run":
        return _cmd_run(root, args)
    if args.command == "doctor":
        return _cmd_doctor(json_output=args.json)
    if args.command == "docs-check":
        return _cmd_docs_check(root, json_output=args.json)
    if args.command == "fixture-hygiene":
        return _cmd_fixture_hygiene(root, json_output=args.json)
    if args.command == "release-manifest":
        return _cmd_release_manifest(root, output=args.output, artifact_dir=args.artifact_dir, json_output=args.json)
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
    hold_seconds = None
    if args.hold:
        hold_seconds = -1.0
    if args.hold_seconds is not None:
        hold_seconds = args.hold_seconds
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


def _random_compatible_combination_sets(root: Path, *, count: int, size: int) -> list[list[Path]]:
    if count <= 0:
        raise ValueError("--random-compatible-combinations must be positive")
    if size < 2:
        raise ValueError("--random-combination-size must be at least 2")
    packages = [load_scenario_package(path) for path in list_scenario_packages(root)]
    groups: dict[str, list[Any]] = defaultdict(list)
    for package in packages:
        axes = package.spec.get("variant_axes", {})
        collection_modes = axes.get("collection_mode", []) if isinstance(axes, dict) else []
        if "real" not in collection_modes:
            continue
        archetype = str(package.spec.get("environment_archetype") or "")
        if archetype:
            groups[archetype].append(package)
    eligible = [
        (archetype, sorted(archetype_packages, key=lambda package: package.name), comb(len(archetype_packages), size))
        for archetype, archetype_packages in sorted(groups.items())
        if len(archetype_packages) >= size
    ]
    total = sum(group_count for *_group, group_count in eligible)
    if not eligible:
        raise ValueError(f"no compatible scenario groups can satisfy --random-combination-size {size}")
    if count > total:
        raise ValueError(f"requested {count} random combinations, but only {total} compatible combinations exist")

    rng = random.SystemRandom()
    selected: list[list[Path]] = []
    seen: set[tuple[str, ...]] = set()
    attempts = 0
    max_attempts = max(100, count * 50)
    while len(selected) < count and attempts < max_attempts:
        attempts += 1
        _archetype, archetype_packages = _weighted_random_group(eligible, rng)
        sampled = sorted(rng.sample(archetype_packages, size), key=lambda package: package.name)
        key = tuple(str(package.path.resolve()) for package in sampled)
        if key in seen:
            continue
        seen.add(key)
        selected.append([package.path for package in sampled])
    if len(selected) < count:
        raise ValueError("could not sample enough unique compatible combinations; try a smaller count")
    return selected


def _weighted_random_group(groups: list[tuple[str, list[Any], int]], rng: random.SystemRandom) -> tuple[str, list[Any]]:
    target = rng.randrange(sum(group_count for *_group, group_count in groups))
    cursor = 0
    for archetype, packages, group_count in groups:
        cursor += group_count
        if target < cursor:
            return archetype, packages
    archetype, packages, _group_count = groups[-1]
    return archetype, packages


def _resolve_cli_path(root: Path, path: Path) -> Path:
    return path if path.is_absolute() else root / path


def _is_batch_run(combination_sets: list[list[Path]], source: dict[str, Any]) -> bool:
    return len(combination_sets) > 1 or bool(source.get("random")) or bool(source.get("specified") and source["specified"] > 1)


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
    blocked = [run for run in runs if run.get("blocked")]
    return {
        "kind": "IncidentRunBatch",
        "batch": True,
        "count": len(runs),
        "generated": not blocked,
        "blocked": bool(blocked),
        "generated_count": len(runs) - len(blocked),
        "blocked_count": len(blocked),
        "collection_mode": collection_mode or "fixture",
        "combination_source": source,
        "runs": runs,
    }


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
        print(f"artifacts={len(manifest['artifacts'])}")
    return 0


def _print_run_result(result: dict[str, Any]) -> None:
    if result.get("batch"):
        status = "blocked" if result.get("blocked") else "generated"
        print(f"{status}\tbatch\t{result.get('collection_mode')}")
        print(
            f"runs={result.get('count')}\tgenerated={result.get('generated_count')}\t"
            f"blocked={result.get('blocked_count')}"
        )
        for index, run in enumerate(result.get("runs", []), start=1):
            run_status = "blocked" if run.get("blocked") else "generated"
            print(f"run[{index}]={run_status}\t{run.get('scenario')}\t{run.get('collection_mode')}")
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
    for fixture in result.get("fixtures", []):
        print(f"fixture={fixture}")
    for failure in result.get("blocking_reasons", []):
        print(f"blocking_reason={failure}")


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
