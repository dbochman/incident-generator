"""Command line interface for the incident generator."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .scenarios import (
    COLLECTION_MODES,
    build_catalog_report,
    default_variant_selection,
    list_scenario_packages,
    load_scenario_package,
    parse_variant_args,
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
    run_parser.add_argument("--scenario", required=True, type=Path)
    run_parser.add_argument("--variant", action="append", dest="variants", help="Variant override as axis=value")
    run_parser.add_argument("--collection-mode", choices=sorted(COLLECTION_MODES))
    run_parser.add_argument("--incident-id")
    run_parser.add_argument("--incident-session-id", default="incident-generator-run")
    run_parser.add_argument("--require-tools", action="store_true", help="Do not fall back to fixture mode if real tools are absent")
    run_parser.add_argument("--hold", action="store_true", help="Keep real infrastructure up until interrupted, then tear down")
    run_parser.add_argument("--hold-seconds", type=float, help="Keep real infrastructure up for N seconds, then tear down")
    run_parser.add_argument("--json", action="store_true", help="Emit JSON")

    doctor_parser = subparsers.add_parser("doctor", help="Show local tool availability for real modes")
    doctor_parser.add_argument("--json", action="store_true", help="Emit JSON")

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
    scenario_path = args.scenario if args.scenario.is_absolute() else root / args.scenario
    try:
        variants = parse_variant_args(args.variants)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    hold_seconds = None
    if args.hold:
        hold_seconds = -1.0
    if args.hold_seconds is not None:
        hold_seconds = args.hold_seconds
    result = stand_up_incident_environment(
        load_scenario_package(scenario_path),
        variants=variants,
        collection_mode=args.collection_mode,
        incident_id=args.incident_id,
        incident_session_id=args.incident_session_id,
        require_tools=args.require_tools,
        workdir=root,
        hold_seconds=hold_seconds,
    )
    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        _print_run_result(result)
    return 1 if result.get("blocked") else 0


def _cmd_doctor(*, json_output: bool) -> int:
    import shutil

    tools = {name: bool(shutil.which(name)) for name in ("docker", "kind", "kubectl", "helm", "curl")}
    if json_output:
        print(json.dumps({"tools": tools}, indent=2, sort_keys=True))
    else:
        for name, present in tools.items():
            print(f"{'ok' if present else 'missing'}\t{name}")
    return 0


def _print_run_result(result: dict[str, Any]) -> None:
    status = "blocked" if result.get("blocked") else "generated"
    print(f"{status}\t{result.get('scenario')}\t{result.get('collection_mode')}")
    for key in ("incident_id", "environment_archetype", "fixture"):
        if result.get(key):
            print(f"{key}={result[key]}")
    for failure in result.get("blocking_reasons", []):
        print(f"blocking_reason={failure}")


def _format_counts(counts: dict[str, int]) -> str:
    return ",".join(f"{key}:{value}" for key, value in sorted(counts.items()))
