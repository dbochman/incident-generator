#!/usr/bin/env python3
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
RUNNER_PATH = ROOT / "harness/ecommerce-lite/chart/files/loadgen_runner.py"


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a deterministic ecommerce-lite load-generator preview.")
    parser.add_argument("--values", type=Path, default=ROOT / "harness/ecommerce-lite/chart/values.yaml")
    parser.add_argument("--release", default="ecommerce-lite")
    parser.add_argument("--namespace", default="ecommerce")
    parser.add_argument("--duration-seconds", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    values = yaml.safe_load(args.values.read_text(encoding="utf-8"))
    runner = _load_runner()
    profile = values["trafficProfile"]
    loadgen = values["loadGenerator"]
    duration_seconds = args.duration_seconds or int(loadgen["durationSeconds"])
    preview_limit = args.limit or int(loadgen["previewRequests"])
    targets = runner.build_targets(loadgen["targetTemplates"], release=args.release, namespace=args.namespace)
    plan = runner.generate_plan(profile, targets, duration_seconds=duration_seconds, preview_limit=preview_limit)
    print(json.dumps(plan, indent=2, sort_keys=True))
    return 0


def _load_runner():
    spec = importlib.util.spec_from_file_location("ecommerce_lite_loadgen_runner", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load {RUNNER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


if __name__ == "__main__":
    raise SystemExit(main())
