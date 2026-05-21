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
from .benchmark_result_helpers import write_json_file as _write_json_file
from .artifact_registry import (
    ArtifactRegistryError,
    append_registry_entry,
    backfill_registry_payload,
    parse_env_assignments,
    registry_check_payload,
    registry_markdown_check_payload,
    render_registry_markdown,
    write_registry_markdown,
)
from .benchmark_runner import (
    BenchmarkRunnerError,
    DEFAULT_AGENT_ADAPTER_BENCHMARK_SET_RELATIVE,
    DEFAULT_AGENT_ADAPTER_EXCHANGE_RELATIVE,
    DEFAULT_SKILL_EXPOSURE,
    parse_evidence_role_expectations,
    run_agent_adapter_benchmark,
    run_agent_adapter_benchmark_set,
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
from .crisismode_adapter import (
    DEFAULT_CRISISMODE_COMPATIBILITY_BENCHMARK_SET_RELATIVE,
    CrisisModeAdapterError,
    build_crisismode_adapter_response,
    run_crisismode_adapter_jsonl,
)
from .deterministic_replay_results import (
    DEFAULT_DETERMINISTIC_REPLAY_BENCHMARK_SET_ID,
    DEFAULT_DETERMINISTIC_REPLAY_SUMMARY_RELATIVE,
    DeterministicReplayResultError,
    render_deterministic_replay_result,
)
from .evidence_discipline_combos import (
    DEFAULT_EVIDENCE_DISCIPLINE_COMBOS_RELATIVE,
    render_evidence_discipline_combo_report,
)
from .experience import ExperienceError, run_follow_experience, run_tail_experience
from .experience_challenge import parse_challenge_answers, run_tail_challenge
from .judge_packs import (
    DEFAULT_AGENT_ADAPTER_JUDGE_PACKS_RELATIVE,
    JudgePackError,
    load_judge_pack_report,
    select_judge_pack,
)
from .llm_smoke_results import (
    DEFAULT_LLM_SMOKE_FIXTURE_SUMMARY_RELATIVE,
    DEFAULT_LLM_SMOKE_LIVE_SUMMARY_RELATIVE,
    DEFAULT_LLM_SMOKE_RESULT_BENCHMARK_SET_ID,
    LLMSmokeResultError,
    render_llm_smoke_result,
)
from .noisy_fixtures import render_noisy_fixture_bundle
from .noisy_live_results import (
    DEFAULT_NOISY_LIVE_REGISTRY_RELATIVE,
    DEFAULT_NOISY_LIVE_RESULT_BENCHMARK_SET_ID,
    DEFAULT_NOISY_LIVE_RUN_ID,
    NoisyLiveResultError,
    render_noisy_live_result,
)
from .noisy_partial_failures import DEFAULT_PACK_RELATIVE, render_noisy_partial_failure_pack
from .noisy_smoke import DEFAULT_SMOKE_RELATIVE, render_noisy_smoke_report
from .progress import OperatorProgressReporter, default_artifact_dir
from .release import build_benchmark_set_listing, write_release_manifest
from .recovery_benchmarks import (
    DEFAULT_RECOVERY_BENCHMARK_RELATIVE,
    render_recovery_after_diagnosis_benchmark,
)
from .result_comparison import (
    BenchmarkResultComparisonError,
    build_result_comparison,
    render_result_comparison_markdown,
    result_comparison_check_payload,
    write_result_comparison_markdown,
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
    resolve_project_root,
    scenarios_are_compatible_for_mode,
    stand_up_combinatorial_incident_environment,
    stand_up_incident_environment,
    validate_scenario_package,
)
from .skill_drill_export import (
    DEFAULT_GOLDEN_RESPONSE_SEEDS_RELATIVE,
    DEFAULT_INCORRECT_RESPONSE_SEEDS_RELATIVE,
    DEFAULT_SKILL_DRILL_OUTPUT_RELATIVE,
    SkillDrillExportError,
    export_skill_drill_bundles,
)
from .temporal_benchmarks import DEFAULT_TEMPORAL_MODEL_RELATIVE, render_temporal_benchmark_model
from .training_curriculum import (
    DEFAULT_TRAINING_CURRICULUM_RELATIVE,
    TrainingCurriculumError,
    build_training_curriculum,
)


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

    crisismode_adapter_parser = subparsers.add_parser(
        "crisismode-adapter",
        help="Read one agent-adapter v1 request on stdin and emit a CrisisMode-compatible response",
    )
    crisismode_adapter_parser.add_argument(
        "--stdio-jsonl",
        action="store_true",
        help="Use the v2 investigation-session stdio JSONL protocol instead of v1 single JSON",
    )

    crisismode_compatibility_parser = subparsers.add_parser(
        "crisismode-compatibility",
        help="Run the checked CrisisMode compatibility benchmark set and emit a report",
    )
    crisismode_compatibility_parser.add_argument(
        "--benchmark-set",
        type=Path,
        default=DEFAULT_CRISISMODE_COMPATIBILITY_BENCHMARK_SET_RELATIVE,
        help=f"CrisisMode compatibility benchmark-set YAML path; defaults to {DEFAULT_CRISISMODE_COMPATIBILITY_BENCHMARK_SET_RELATIVE}",
    )
    crisismode_compatibility_parser.add_argument("--created-at", help="Created-at timestamp override")
    crisismode_compatibility_parser.add_argument(
        "--crisismode-repo",
        type=Path,
        help="Optional CrisisMode checkout path used to discover built-in agents and detect coverage gaps",
    )
    crisismode_compatibility_parser.add_argument(
        "--adapter-command",
        help=(
            "Optional real CrisisMode adapter command to run with the adapter request JSON on stdin; "
            "defaults to the local incident-generator shim"
        ),
    )
    crisismode_compatibility_parser.add_argument(
        "--strict",
        action="store_true",
        help="Return nonzero when the compatibility gate fails",
    )
    crisismode_compatibility_parser.add_argument("--output", type=Path, help="Write compatibility report JSON to this path")
    crisismode_compatibility_parser.add_argument("--json", action="store_true", help="Emit JSON")

    crisismode_provider_smoke_parser = subparsers.add_parser(
        "crisismode-provider-smoke",
        help="Validate an OpenAI-compatible CrisisMode provider before live compatibility probes",
    )
    crisismode_provider_smoke_parser.add_argument(
        "--base-url",
        help="OpenAI-compatible provider base URL; defaults to CRISISMODE_AI_BASE_URL, NVIDIA_BASE_URL, or NVIDIA Gateway",
    )
    crisismode_provider_smoke_parser.add_argument(
        "--model",
        help="Provider model id; defaults to CRISISMODE_AI_MODEL or NVIDIA_MODEL",
    )
    crisismode_provider_smoke_parser.add_argument(
        "--api-key-env",
        action="append",
        help=(
            "Environment variable containing the provider key; repeat to allow fallbacks. "
            "Defaults to CRISISMODE_AI_API_KEY, NVIDIA_API_KEY, NVIDIA_INFERENCE_API_KEY"
        ),
    )
    crisismode_provider_smoke_parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=30.0,
        help="HTTP timeout for each provider smoke request",
    )
    crisismode_provider_smoke_parser.add_argument(
        "--prompt",
        default="Reply with exactly: crisismode provider smoke ok",
        help="Prompt used for the completion smoke request",
    )
    crisismode_provider_smoke_parser.add_argument("--output", type=Path, help="Write provider smoke JSON to this path")
    crisismode_provider_smoke_parser.add_argument("--json", action="store_true", help="Emit JSON")

    benchmark_runner_parser = subparsers.add_parser(
        "benchmark-runner",
        help="Run or replay an external agent adapter exchange and emit benchmark results",
    )
    benchmark_runner_parser.add_argument(
        "--benchmark-set",
        type=Path,
        nargs="?",
        const=DEFAULT_AGENT_ADAPTER_BENCHMARK_SET_RELATIVE,
        help=(
            "Agent adapter benchmark-set YAML path; defaults to "
            f"{DEFAULT_AGENT_ADAPTER_BENCHMARK_SET_RELATIVE} when provided without a value"
        ),
    )
    benchmark_runner_parser.add_argument(
        "--exchange",
        type=Path,
        help=f"Agent adapter exchange JSON path; defaults to {DEFAULT_AGENT_ADAPTER_EXCHANGE_RELATIVE}",
    )
    benchmark_runner_parser.add_argument(
        "--adapter-command",
        help=(
            "Optional local command to run as an adapter; v1 sends request JSON on stdin, "
            "v2 uses stdio JSONL session messages"
        ),
    )
    benchmark_runner_parser.add_argument(
        "--input-mode",
        default="redacted-evidence-bundle",
        choices=[
            "redacted-evidence-bundle",
            "redacted_evidence_bundle",
            "investigation-session",
            "sandboxed_investigation_session",
        ],
        help="Adapter input mode; v1 redacted evidence bundle remains the default",
    )
    benchmark_runner_parser.add_argument(
        "--adapter-protocol",
        default="json",
        choices=["json", "stdio-jsonl"],
        help="Adapter transport protocol; investigation-session requires stdio-jsonl",
    )
    benchmark_runner_parser.add_argument(
        "--skill-exposure",
        default=DEFAULT_SKILL_EXPOSURE.replace("_", "-"),
        choices=["none", "catalog-index", "routed-procedure", "routed-full", "full-catalog"],
        help="Skill exposure treatment for investigation-session mode",
    )
    benchmark_runner_parser.add_argument(
        "--execute-real-provider-tools",
        action="store_true",
        help="Execute v2 typed tool requests through read-only provider contracts instead of fixture replay",
    )
    benchmark_runner_parser.add_argument(
        "--provider-profile",
        help="Provider profile required with --execute-real-provider-tools, such as harness-local",
    )
    benchmark_runner_parser.add_argument(
        "--allow-sensitive-tools",
        action="store_true",
        help="Permit sensitive read-only provider adapters during real provider investigation sessions",
    )
    benchmark_runner_parser.add_argument(
        "--judge-pack",
        help="Optional judge-pack id from the checked judge-pack manifest, such as deterministic-local",
    )
    benchmark_runner_parser.add_argument(
        "--judge-packs",
        type=Path,
        default=DEFAULT_AGENT_ADAPTER_JUDGE_PACKS_RELATIVE,
        help=f"Judge-pack manifest path; defaults to {DEFAULT_AGENT_ADAPTER_JUDGE_PACKS_RELATIVE}",
    )
    benchmark_runner_parser.add_argument(
        "--expected-hypothesis",
        action="append",
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
    benchmark_runner_parser.add_argument("--artifact-dir", type=Path, help="Retain result, summary, events, and case artifacts")
    benchmark_runner_parser.add_argument("--output", type=Path, help="Write benchmark-result JSON to this path")
    benchmark_runner_parser.add_argument("--json", action="store_true", help="Emit JSON")

    experience_parser = subparsers.add_parser(
        "experience",
        help="Replay retained incident artifacts as a terminal tail experience",
    )
    experience_parser.add_argument("--artifact-dir", type=Path, required=True, help="Artifact directory to replay")
    experience_parser.add_argument("--mode", choices=["tail", "challenge", "follow"], default="tail", help="Experience mode")
    experience_parser.add_argument("--output-dir", type=Path, help="Optional directory for experience.json and timeline.ndjson")
    experience_parser.add_argument("--generated-at", help="Generated-at timestamp override for deterministic tests")
    experience_parser.add_argument("--speed", type=float, default=1.0, help="Playback speed multiplier")
    experience_parser.add_argument(
        "--max-gap-seconds",
        type=float,
        default=30.0,
        help="Insert a gap line and cap compressed sleeps when source gaps exceed this many seconds",
    )
    experience_parser.add_argument("--no-sleep", action="store_true", help="Print playback lines without sleeping")
    experience_parser.add_argument("--no-play", action="store_true", help="Write artifacts without printing playback lines")
    experience_parser.add_argument(
        "--answers",
        help="Comma-separated one-based choice numbers for non-interactive challenge runs",
    )
    experience_parser.add_argument(
        "--reveal-answers",
        action="store_true",
        help="With --mode challenge, skip input and reveal the expected answers after replay",
    )
    experience_parser.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=1.0,
        help="Follow mode polling interval for appended retained artifact events",
    )
    experience_parser.add_argument(
        "--follow-timeout-seconds",
        type=float,
        help="Maximum follow mode wall-clock duration before returning or failing",
    )
    experience_parser.add_argument(
        "--follow-idle-timeout-seconds",
        type=float,
        help="Stop follow mode after this many seconds without new events",
    )

    judge_packs_parser = subparsers.add_parser("judge-packs", help="List checked benchmark judge-pack selections")
    judge_packs_parser.add_argument(
        "--judge-packs",
        type=Path,
        default=DEFAULT_AGENT_ADAPTER_JUDGE_PACKS_RELATIVE,
        help=f"Judge-pack manifest path; defaults to {DEFAULT_AGENT_ADAPTER_JUDGE_PACKS_RELATIVE}",
    )
    judge_packs_parser.add_argument("--pack-id", help="Show one judge pack by id")
    judge_packs_parser.add_argument("--output", type=Path, help="Write judge-pack report JSON to this path")
    judge_packs_parser.add_argument("--json", action="store_true", help="Emit JSON")

    deterministic_replay_parser = subparsers.add_parser(
        "deterministic-replay-result",
        help="Convert deterministic validated-combo replay summaries into benchmark-result JSON",
    )
    deterministic_replay_parser.add_argument(
        "--summary",
        type=Path,
        default=DEFAULT_DETERMINISTIC_REPLAY_SUMMARY_RELATIVE,
        help=f"Validated combo-agent summary path; defaults to {DEFAULT_DETERMINISTIC_REPLAY_SUMMARY_RELATIVE}",
    )
    deterministic_replay_parser.add_argument(
        "--benchmark-set-id",
        default=DEFAULT_DETERMINISTIC_REPLAY_BENCHMARK_SET_ID,
        help=f"Benchmark set id to record; defaults to {DEFAULT_DETERMINISTIC_REPLAY_BENCHMARK_SET_ID}",
    )
    deterministic_replay_parser.add_argument("--name", help="Benchmark set display name")
    deterministic_replay_parser.add_argument("--result-id", help="Stable result id override")
    deterministic_replay_parser.add_argument("--created-at", help="ISO-8601 timestamp override")
    deterministic_replay_parser.add_argument(
        "--collection-mode",
        choices=["fixture", "real"],
        default="real",
        help="Collection mode to record for replayed generated incidents",
    )
    deterministic_replay_parser.add_argument(
        "--archetype",
        choices=["fixture", "kind", "linux-vm", "mixed", "unknown"],
        default="kind",
        help="Generated incident archetype to record",
    )
    deterministic_replay_parser.add_argument("--output", type=Path, help="Write benchmark-result JSON to this path")
    deterministic_replay_parser.add_argument("--json", action="store_true", help="Emit JSON")

    llm_smoke_result_parser = subparsers.add_parser(
        "llm-smoke-result",
        help="Convert recorded benchmark-combo LLM smoke summaries into benchmark-result JSON",
    )
    llm_smoke_result_parser.add_argument(
        "--fixture-summary",
        type=Path,
        default=DEFAULT_LLM_SMOKE_FIXTURE_SUMMARY_RELATIVE,
        help=f"Fixture-backed smoke summary; defaults to {DEFAULT_LLM_SMOKE_FIXTURE_SUMMARY_RELATIVE}",
    )
    llm_smoke_result_parser.add_argument(
        "--live-summary",
        type=Path,
        default=DEFAULT_LLM_SMOKE_LIVE_SUMMARY_RELATIVE,
        help=f"Live-provider smoke summary; defaults to {DEFAULT_LLM_SMOKE_LIVE_SUMMARY_RELATIVE}",
    )
    llm_smoke_result_parser.add_argument(
        "--include",
        choices=["fixture", "live", "both"],
        default="both",
        help="Which recorded LLM smoke summaries to include",
    )
    llm_smoke_result_parser.add_argument(
        "--benchmark-set-id",
        default=DEFAULT_LLM_SMOKE_RESULT_BENCHMARK_SET_ID,
        help=f"Benchmark set id override; defaults to {DEFAULT_LLM_SMOKE_RESULT_BENCHMARK_SET_ID}",
    )
    llm_smoke_result_parser.add_argument("--name", help="Benchmark set display name")
    llm_smoke_result_parser.add_argument("--result-id", help="Stable result id override")
    llm_smoke_result_parser.add_argument("--created-at", help="ISO-8601 timestamp override")
    llm_smoke_result_parser.add_argument("--output", type=Path, help="Write benchmark-result JSON to this path")
    llm_smoke_result_parser.add_argument("--json", action="store_true", help="Emit JSON")

    noisy_live_result_parser = subparsers.add_parser(
        "noisy-live-result",
        help="Convert retained noisy live artifact-registry entries into benchmark-result JSON",
    )
    noisy_live_result_parser.add_argument(
        "--registry",
        type=Path,
        default=DEFAULT_NOISY_LIVE_REGISTRY_RELATIVE,
        help=f"Artifact registry path; defaults to {DEFAULT_NOISY_LIVE_REGISTRY_RELATIVE}",
    )
    noisy_live_result_parser.add_argument(
        "--run-id",
        default=DEFAULT_NOISY_LIVE_RUN_ID,
        help=f"Noisy live run id to emit; defaults to {DEFAULT_NOISY_LIVE_RUN_ID}",
    )
    noisy_live_result_parser.add_argument(
        "--benchmark-set-id",
        default=None,
        help=(
            "Benchmark set id override; defaults to the artifact registry entry for --run-id "
            f"({DEFAULT_NOISY_LIVE_RESULT_BENCHMARK_SET_ID} for the default retained run)"
        ),
    )
    noisy_live_result_parser.add_argument("--name", help="Benchmark set display name")
    noisy_live_result_parser.add_argument("--result-id", help="Stable result id override")
    noisy_live_result_parser.add_argument("--created-at", help="ISO-8601 timestamp override")
    noisy_live_result_parser.add_argument("--output", type=Path, help="Write benchmark-result JSON to this path")
    noisy_live_result_parser.add_argument("--json", action="store_true", help="Emit JSON")

    benchmark_sets_parser = subparsers.add_parser(
        "benchmark-sets",
        help="List checked benchmark sets and aliases without live infrastructure",
    )
    benchmark_sets_parser.add_argument("--json", action="store_true", help="Emit JSON")

    result_comparison_parser = subparsers.add_parser(
        "result-comparison",
        help="Render a Markdown comparison view from benchmark-result JSON payloads",
    )
    result_comparison_parser.add_argument(
        "--result",
        action="append",
        type=Path,
        help="Benchmark-result JSON path; repeat to compare multiple payloads. Defaults to checked local payloads.",
    )
    result_comparison_parser.add_argument("--created-at", help="Created-at timestamp for checked default payloads")
    result_comparison_output_group = result_comparison_parser.add_mutually_exclusive_group()
    result_comparison_output_group.add_argument("--output", type=Path, help="Write Markdown output to this path")
    result_comparison_output_group.add_argument("--check-output", type=Path, help="Fail if Markdown output is stale")
    result_comparison_parser.add_argument("--json", action="store_true", help="Emit JSON")

    curriculum_parser = subparsers.add_parser(
        "training-curriculum",
        help="Validate and summarize the checked training curriculum ordering",
    )
    curriculum_parser.add_argument(
        "--curriculum",
        type=Path,
        default=DEFAULT_TRAINING_CURRICULUM_RELATIVE,
        help=f"Training curriculum manifest path; defaults to {DEFAULT_TRAINING_CURRICULUM_RELATIVE}",
    )
    curriculum_parser.add_argument(
        "--golden-seeds",
        type=Path,
        default=DEFAULT_GOLDEN_RESPONSE_SEEDS_RELATIVE,
        help=f"Golden response seed manifest path; defaults to {DEFAULT_GOLDEN_RESPONSE_SEEDS_RELATIVE}",
    )
    curriculum_parser.add_argument(
        "--incorrect-seeds",
        type=Path,
        default=DEFAULT_INCORRECT_RESPONSE_SEEDS_RELATIVE,
        help=f"Incorrect response seed manifest path; defaults to {DEFAULT_INCORRECT_RESPONSE_SEEDS_RELATIVE}",
    )
    curriculum_parser.add_argument("--json", action="store_true", help="Emit JSON")

    drill_export_parser = subparsers.add_parser(
        "skill-drill-export",
        help="Export portable benchmark-derived skill drill bundles",
    )
    drill_export_parser.add_argument(
        "--golden-seeds",
        type=Path,
        default=DEFAULT_GOLDEN_RESPONSE_SEEDS_RELATIVE,
        help=f"Golden response seed manifest path; defaults to {DEFAULT_GOLDEN_RESPONSE_SEEDS_RELATIVE}",
    )
    drill_export_parser.add_argument(
        "--incorrect-seeds",
        type=Path,
        default=DEFAULT_INCORRECT_RESPONSE_SEEDS_RELATIVE,
        help=f"Incorrect response seed manifest path; defaults to {DEFAULT_INCORRECT_RESPONSE_SEEDS_RELATIVE}",
    )
    drill_export_parser.add_argument(
        "--curriculum",
        type=Path,
        default=DEFAULT_TRAINING_CURRICULUM_RELATIVE,
        help=f"Training curriculum manifest path; defaults to {DEFAULT_TRAINING_CURRICULUM_RELATIVE}",
    )
    drill_export_parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_SKILL_DRILL_OUTPUT_RELATIVE,
        help=f"Training bundle output directory; defaults to {DEFAULT_SKILL_DRILL_OUTPUT_RELATIVE}",
    )
    drill_export_parser.add_argument("--created-at", help="Created-at timestamp override for deterministic exports")
    drill_export_parser.add_argument("--json", action="store_true", help="Emit JSON")

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
    registry_backfill_parser = registry_subparsers.add_parser("backfill", help="Backfill retained benchmark runs from a manifest")
    registry_backfill_parser.add_argument("--manifest", type=Path, required=True, help="Backfill manifest YAML path")
    registry_backfill_parser.add_argument("--registry", type=Path, required=True, help="Registry JSON path to create or append")
    registry_backfill_mode = registry_backfill_parser.add_mutually_exclusive_group(required=True)
    registry_backfill_mode.add_argument("--dry-run", action="store_true", help="Validate and preview entries without writing")
    registry_backfill_mode.add_argument("--write", action="store_true", help="Append validated entries to the registry")
    registry_backfill_parser.add_argument("--created-at", help="Entry timestamp override, primarily for deterministic tests")
    registry_backfill_parser.add_argument("--json", action="store_true", help="Emit JSON")
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
    root = resolve_project_root(args.root)

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
    if args.command == "crisismode-adapter":
        return _cmd_crisismode_adapter(args)
    if args.command == "crisismode-compatibility":
        return _cmd_crisismode_compatibility(root, args)
    if args.command == "crisismode-provider-smoke":
        return _cmd_crisismode_provider_smoke(args)
    if args.command == "benchmark-runner":
        return _cmd_benchmark_runner(root, args)
    if args.command == "experience":
        return _cmd_experience(root, args)
    if args.command == "judge-packs":
        return _cmd_judge_packs(root, args)
    if args.command == "deterministic-replay-result":
        return _cmd_deterministic_replay_result(root, args)
    if args.command == "llm-smoke-result":
        return _cmd_llm_smoke_result(root, args)
    if args.command == "noisy-live-result":
        return _cmd_noisy_live_result(root, args)
    if args.command == "benchmark-sets":
        return _cmd_benchmark_sets(root, json_output=args.json)
    if args.command == "result-comparison":
        return _cmd_result_comparison(root, args)
    if args.command == "training-curriculum":
        return _cmd_training_curriculum(root, args)
    if args.command == "skill-drill-export":
        return _cmd_skill_drill_export(root, args)
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


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def _cmd_crisismode_adapter(args: argparse.Namespace) -> int:
    try:
        if args.stdio_jsonl:
            run_crisismode_adapter_jsonl(sys.stdin, sys.stdout)
            return 0
        raw = sys.stdin.read()
        payload = json.loads(raw or "{}")
        if not isinstance(payload, dict):
            raise CrisisModeAdapterError("adapter input must be a JSON object")
        _print_json(build_crisismode_adapter_response(payload))
    except (CrisisModeAdapterError, json.JSONDecodeError) as exc:
        print(f"crisismode-adapter error: {exc}", file=sys.stderr)
        return 2
    return 0


def _cmd_crisismode_compatibility(root: Path, args: argparse.Namespace) -> int:
    from .crisismode_compatibility import CrisisModeCompatibilityError, render_crisismode_compatibility_report

    try:
        payload = render_crisismode_compatibility_report(
            root,
            benchmark_set_path=args.benchmark_set,
            adapter_command=args.adapter_command,
            crisismode_repo=args.crisismode_repo,
            created_at=args.created_at,
        )
    except (BenchmarkRunnerError, CrisisModeCompatibilityError, JudgePackError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"crisismode-compatibility error: {exc}", file=sys.stderr)
        return 2
    if args.output:
        _write_json_file(args.output, payload)
    if args.json:
        _print_json(payload)
    else:
        aggregate = payload["benchmark_result"]["aggregate"]
        validation = payload["response_validation"]
        print(
            "crisismode_compatibility"
            f"\tcases={aggregate['case_count']}"
            f"\tpassed={aggregate['passed_count']}"
            f"\tfailed={aggregate['failed_count']}"
            f"\tschema_valid={validation['valid_count']}/{validation['case_count']}"
        )
    return 1 if args.strict and not payload["ci_gate"]["passed"] else 0


def _cmd_crisismode_provider_smoke(args: argparse.Namespace) -> int:
    from .crisismode_compatibility import render_crisismode_provider_smoke

    payload = render_crisismode_provider_smoke(
        base_url=args.base_url,
        model=args.model,
        api_key_env=tuple(args.api_key_env)
        if args.api_key_env
        else ("CRISISMODE_AI_API_KEY", "NVIDIA_API_KEY", "NVIDIA_INFERENCE_API_KEY"),
        timeout_seconds=args.timeout_seconds,
        prompt=args.prompt,
    )
    if args.output:
        _write_json_file(args.output, payload)
    if args.json:
        _print_json(payload)
    else:
        checks = ",".join(f"{check['name']}={'ok' if check.get('passed') else 'fail'}" for check in payload["checks"])
        print(
            "crisismode_provider_smoke"
            f"\tpassed={str(payload['passed']).lower()}"
            f"\tbase_url={payload['base_url']}"
            f"\tmodel={payload.get('model') or '-'}"
            f"\tchecks={checks}"
        )
    return 0 if payload["passed"] else 1


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
        _print_json({"count": len(rows), "scenarios": rows})
    else:
        for row in rows:
            print(f"{row['name']}\t{row['environment_archetype']}\t{row['path']}")
        print(f"count={len(rows)}")
    return 0


def _cmd_catalog(root: Path, *, json_output: bool) -> int:
    report = build_catalog_report(root)
    if json_output:
        _print_json(report)
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
        _print_json({"valid": not failed, "count": len(rows), "scenarios": rows})
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
        _print_json(report)
    else:
        _print_plan_report(report)
    return 0


def _build_compatibility_plan_report(root: Path, args: argparse.Namespace) -> dict[str, Any]:
    collection_mode = args.collection_mode or "real"
    explicit_sets = _resolve_explicit_combination_sets(root, args)
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


def _resolve_explicit_combination_sets(root: Path, args: argparse.Namespace) -> list[list[Path]]:
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
        _print_json(result)
    else:
        _print_run_result(result)
    return 1 if result.get("blocked") else 0


def _emit_json_payload(
    root: Path,
    args: argparse.Namespace,
    payload: Any,
    *,
    summary_lines: list[str],
) -> None:
    output = getattr(args, "output", None)
    if output is not None:
        resolved_output = _resolve_cli_path(root, output)
        _write_json_file(resolved_output, payload)
    if getattr(args, "json", False) or output is None:
        _print_json(payload)
    else:
        for line in summary_lines:
            print(line)


def _emit_report_payload(
    root: Path,
    args: argparse.Namespace,
    payload: Any,
    *,
    label: str,
    metrics: dict[str, Any],
) -> None:
    _emit_json_payload(
        root,
        args,
        payload,
        summary_lines=[f"{label}={args.output}", *(f"{key}={value}" for key, value in metrics.items())],
    )


def _emit_checked_report_payload(
    root: Path,
    args: argparse.Namespace,
    payload: dict[str, Any],
    *,
    label: str,
    metrics: dict[str, Any],
) -> int:
    _emit_report_payload(root, args, payload, label=label, metrics=metrics)
    return 0 if payload.get("passed") else 1


def _emit_benchmark_result_payload(
    root: Path,
    args: argparse.Namespace,
    payload: dict[str, Any],
    *,
    label: str,
    first_line_metrics: dict[str, Any] | None = None,
    result_line_metrics: dict[str, Any],
) -> None:
    benchmark_set = payload["benchmark_set"]["benchmark_set_id"]
    first_line = _tabbed(
        f"{label}={args.output}",
        f"benchmark_set={benchmark_set}",
        *(f"{key}={value}" for key, value in (first_line_metrics or {}).items()),
    )
    result_line = _tabbed(*(f"{key}={value}" for key, value in result_line_metrics.items()))
    _emit_json_payload(root, args, payload, summary_lines=[first_line, result_line])


def _tabbed(*parts: str) -> str:
    return "\t".join(parts)


def _cmd_noisy_fixture(root: Path, args: argparse.Namespace) -> int:
    package = load_scenario_package(_resolve_cli_path(root, args.scenario))
    payload = render_noisy_fixture_bundle(
        root,
        package,
        seed=args.seed,
        max_noise_sources=args.max_noise_sources,
    )
    _emit_report_payload(
        root,
        args,
        payload,
        label="noisy_fixture_manifest",
        metrics=dict(artifact_hash=payload["artifact_hash"], noise_sources=len(payload["noise_profile"]["source_ids"])),
    )
    return 0


def _cmd_noisy_smoke(root: Path, args: argparse.Namespace) -> int:
    payload = render_noisy_smoke_report(
        root,
        smoke_path=args.smoke,
        seed=args.seed,
        max_noise_sources=args.max_noise_sources,
    )
    return _emit_checked_report_payload(
        root,
        args,
        payload,
        label="noisy_smoke_report",
        metrics=dict(artifact_hash=payload["artifact_hash"], passed=payload["passed"], scenario_count=payload["scenario_count"]),
    )


def _cmd_noisy_partial_failures(root: Path, args: argparse.Namespace) -> int:
    payload = render_noisy_partial_failure_pack(
        root,
        pack_path=args.pack,
        seed=args.seed,
        max_noise_sources=args.max_noise_sources,
    )
    return _emit_checked_report_payload(
        root,
        args,
        payload,
        label="noisy_partial_failure_pack_report",
        metrics=dict(artifact_hash=payload["artifact_hash"], passed=payload["passed"], variant_count=payload["variant_count"]),
    )


def _cmd_triple_preview(root: Path, args: argparse.Namespace) -> int:
    payload = render_triple_benchmark_fixture_preview(
        root,
        preview_path=args.preview,
        seed=args.seed,
        selected_count=args.selected_count,
    )
    return _emit_checked_report_payload(
        root,
        args,
        payload,
        label="triple_preview_report",
        metrics=dict(artifact_hash=payload["artifact_hash"], passed=payload["passed"], selected_count=payload["selected_count"]),
    )


def _cmd_pair_preview(root: Path, args: argparse.Namespace) -> int:
    payload = render_random_pair_fixture_preview(
        root,
        preview_path=args.preview,
        seed=args.seed,
        selected_count=args.selected_count,
    )
    return _emit_checked_report_payload(
        root,
        args,
        payload,
        label="pair_preview_report",
        metrics=dict(artifact_hash=payload["artifact_hash"], passed=payload["passed"], selected_count=payload["selected_count"]),
    )


def _cmd_temporal_model(root: Path, args: argparse.Namespace) -> int:
    payload = render_temporal_benchmark_model(root, model_path=args.model)
    return _emit_checked_report_payload(
        root,
        args,
        payload,
        label="temporal_model_report",
        metrics=dict(artifact_hash=payload["artifact_hash"], passed=payload["passed"], phase_count=payload["phase_count"]),
    )


def _cmd_recovery_benchmark(root: Path, args: argparse.Namespace) -> int:
    payload = render_recovery_after_diagnosis_benchmark(root, benchmark_path=args.benchmark)
    return _emit_checked_report_payload(
        root,
        args,
        payload,
        label="recovery_benchmark_report",
        metrics=dict(artifact_hash=payload["artifact_hash"], passed=payload["passed"], case_count=payload["case_count"]),
    )


def _cmd_adversarial_combos(root: Path, args: argparse.Namespace) -> int:
    payload = render_adversarial_combo_report(root, combo_path=args.combos)
    return _emit_checked_report_payload(
        root,
        args,
        payload,
        label="adversarial_combo_report",
        metrics=dict(artifact_hash=payload["artifact_hash"], passed=payload["passed"], combo_count=payload["combo_count"]),
    )


def _cmd_evidence_discipline_combos(root: Path, args: argparse.Namespace) -> int:
    payload = render_evidence_discipline_combo_report(root, combo_path=args.combos)
    return _emit_checked_report_payload(
        root,
        args,
        payload,
        label="evidence_discipline_combo_report",
        metrics=dict(artifact_hash=payload["artifact_hash"], passed=payload["passed"], combo_count=payload["combo_count"]),
    )


def _cmd_conflicting_signal_combos(root: Path, args: argparse.Namespace) -> int:
    payload = render_conflicting_signal_combo_report(root, combo_path=args.combos)
    return _emit_checked_report_payload(
        root,
        args,
        payload,
        label="conflicting_signal_combo_report",
        metrics=dict(artifact_hash=payload["artifact_hash"], passed=payload["passed"], combo_count=payload["combo_count"]),
    )


def _cmd_confidence_calibration(root: Path, args: argparse.Namespace) -> int:
    payload = render_confidence_calibration_report(root, calibration_path=args.calibration)
    return _emit_checked_report_payload(
        root,
        args,
        payload,
        label="confidence_calibration_report",
        metrics=dict(artifact_hash=payload["artifact_hash"], passed=payload["passed"], case_count=payload["case_count"]),
    )


def _cmd_judge_packs(root: Path, args: argparse.Namespace) -> int:
    try:
        payload = load_judge_pack_report(root, judge_packs_path=args.judge_packs, pack_id=args.pack_id)
    except (JudgePackError, OSError, ValueError) as exc:
        print(f"judge-packs error: {exc}", file=sys.stderr)
        return 2
    _emit_json_payload(
        root,
        args,
        payload,
        summary_lines=[f"judge_packs={args.output}\tcount={payload['pack_count']}"],
    )
    return 0


def _cmd_deterministic_replay_result(root: Path, args: argparse.Namespace) -> int:
    try:
        payload = render_deterministic_replay_result(
            root,
            summary_path=args.summary,
            benchmark_set_id=args.benchmark_set_id,
            name=args.name,
            result_id=args.result_id,
            created_at=args.created_at,
            collection_mode=args.collection_mode,
            archetype=args.archetype,
        )
    except (DeterministicReplayResultError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"deterministic-replay-result error: {exc}", file=sys.stderr)
        return 2
    aggregate = payload["aggregate"]
    _emit_benchmark_result_payload(
        root,
        args,
        payload,
        label="deterministic_replay_result",
        result_line_metrics=dict(
            cases=aggregate["case_count"],
            passed=aggregate["passed_count"],
            failed=aggregate["failed_count"],
        ),
    )
    return 0 if payload["aggregate"]["failed_count"] == 0 else 1


def _cmd_llm_smoke_result(root: Path, args: argparse.Namespace) -> int:
    try:
        payload = render_llm_smoke_result(
            root,
            fixture_summary_path=args.fixture_summary,
            live_summary_path=args.live_summary,
            mode=args.include,
            benchmark_set_id=args.benchmark_set_id,
            name=args.name,
            result_id=args.result_id,
            created_at=args.created_at,
        )
    except (LLMSmokeResultError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"llm-smoke-result error: {exc}", file=sys.stderr)
        return 2
    aggregate = payload["aggregate"]
    _emit_benchmark_result_payload(
        root,
        args,
        payload,
        label="llm_smoke_result",
        result_line_metrics=dict(
            cases=aggregate["case_count"],
            entrants=aggregate["entrant_count"],
            passed=aggregate["passed_count"],
            failed=aggregate["failed_count"],
        ),
    )
    return 0 if payload["aggregate"]["failed_count"] == 0 and payload["aggregate"]["blocked_count"] == 0 else 1


def _cmd_noisy_live_result(root: Path, args: argparse.Namespace) -> int:
    try:
        payload = render_noisy_live_result(
            root,
            registry_path=args.registry,
            run_id=args.run_id,
            benchmark_set_id=args.benchmark_set_id,
            name=args.name,
            result_id=args.result_id,
            created_at=args.created_at,
        )
    except (NoisyLiveResultError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"noisy-live-result error: {exc}", file=sys.stderr)
        return 2
    aggregate = payload["aggregate"]
    _emit_benchmark_result_payload(
        root,
        args,
        payload,
        label="noisy_live_result",
        result_line_metrics=dict(
            cases=aggregate["case_count"],
            passed=aggregate["passed_count"],
            failed=aggregate["failed_count"],
        ),
    )
    return 0 if payload["aggregate"]["failed_count"] == 0 and payload["aggregate"]["blocked_count"] == 0 else 1


def _cmd_result_comparison(root: Path, args: argparse.Namespace) -> int:
    result_paths = args.result or None
    try:
        if args.check_output is not None:
            payload = result_comparison_check_payload(
                root,
                output=args.check_output,
                result_paths=result_paths,
                created_at=args.created_at,
            )
            if args.json:
                _print_json(payload)
            elif payload["ok"]:
                print(f"result-comparison ok\toutput={payload['output']}")
            else:
                print(f"result-comparison drift\toutput={payload['output']}")
            return 0 if payload["ok"] else 1
        if args.output is not None:
            write_result_comparison_markdown(
                root,
                output=args.output,
                result_paths=result_paths,
                created_at=args.created_at,
            )
            payload = {"ok": True, "output": str(args.output)}
            if args.json:
                _print_json(payload)
            else:
                print(f"result_comparison={args.output}")
            return 0
        comparison = build_result_comparison(root, result_paths=result_paths, created_at=args.created_at)
        markdown = render_result_comparison_markdown(root, result_paths=result_paths, created_at=args.created_at)
    except (BenchmarkResultComparisonError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"result-comparison error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        _print_json({"ok": True, "comparison": comparison, "markdown": markdown})
    else:
        print(markdown, end="")
    return 0


def _cmd_skill_drill_export(root: Path, args: argparse.Namespace) -> int:
    try:
        payload = export_skill_drill_bundles(
            root,
            output_dir=args.output_dir,
            golden_seeds_path=args.golden_seeds,
            incorrect_seeds_path=args.incorrect_seeds,
            curriculum_path=args.curriculum,
            created_at=args.created_at,
        )
    except (SkillDrillExportError, OSError, ValueError) as exc:
        print(f"skill-drill-export error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        _print_json(payload)
    else:
        print(f"skill_drill_export={payload['manifest_path']}\tbundles={payload['bundle_count']}")
        print(f"incorrect_responses={payload['incorrect_response_count']}")
    return 0


def _cmd_training_curriculum(root: Path, args: argparse.Namespace) -> int:
    try:
        payload = build_training_curriculum(
            root,
            curriculum_path=args.curriculum,
            golden_seeds_path=args.golden_seeds,
            incorrect_seeds_path=args.incorrect_seeds,
        )
    except (TrainingCurriculumError, OSError, ValueError) as exc:
        print(f"training-curriculum error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        _print_json(payload)
    else:
        print(f"training_curriculum={args.curriculum}\tentries={payload['entry_count']}")
        print(f"difficulty_order={','.join(payload['difficulty_order'])}")
        print(f"domains={','.join(sorted({entry['domain'] for entry in payload['entries']}))}")
    return 0


def _cmd_benchmark_runner(root: Path, args: argparse.Namespace) -> int:
    try:
        judge_pack = None
        if args.judge_pack:
            judge_pack = select_judge_pack(root, args.judge_pack, judge_packs_path=args.judge_packs)
        if args.benchmark_set is not None:
            payload = run_agent_adapter_benchmark_set(
                root,
                benchmark_set_path=args.benchmark_set,
                adapter_command=args.adapter_command,
                input_mode=args.input_mode,
                adapter_protocol=args.adapter_protocol,
                skill_exposure=args.skill_exposure,
                judge_pack=judge_pack,
                result_id=args.result_id,
                created_at=args.created_at,
                artifact_dir=args.artifact_dir,
                execute_real_provider_tools=args.execute_real_provider_tools,
                provider_profile_name=args.provider_profile,
                allow_sensitive_tools=args.allow_sensitive_tools,
            )
        else:
            if not args.expected_hypothesis:
                raise BenchmarkRunnerError("--expected-hypothesis is required unless --benchmark-set is used")
            payload = run_agent_adapter_benchmark(
                root,
                exchange_path=args.exchange or DEFAULT_AGENT_ADAPTER_EXCHANGE_RELATIVE,
                adapter_command=args.adapter_command,
                input_mode=args.input_mode,
                adapter_protocol=args.adapter_protocol,
                skill_exposure=args.skill_exposure,
                judge_pack=judge_pack,
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
                artifact_dir=args.artifact_dir,
                execute_real_provider_tools=args.execute_real_provider_tools,
                provider_profile_name=args.provider_profile,
                allow_sensitive_tools=args.allow_sensitive_tools,
            )
    except (BenchmarkRunnerError, JudgePackError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"benchmark-runner error: {exc}", file=sys.stderr)
        return 2
    aggregate = payload["aggregate"]
    _emit_benchmark_result_payload(
        root,
        args,
        payload,
        label="benchmark_runner_result",
        first_line_metrics=dict(cases=aggregate["case_count"], entrants=aggregate["entrant_count"]),
        result_line_metrics=dict(
            result_count=aggregate["result_count"],
            passed=aggregate["passed_count"],
            failed=aggregate["failed_count"],
            blocked=aggregate["blocked_count"],
        ),
    )
    bad_result = any(result.get("state") in {"failed", "blocked", "error"} for result in payload["results"])
    return 0 if not bad_result else 1


def _cmd_experience(root: Path, args: argparse.Namespace) -> int:
    artifact_dir = args.artifact_dir if args.artifact_dir.is_absolute() else root / args.artifact_dir
    output_dir = None
    if args.output_dir is not None:
        output_dir = args.output_dir if args.output_dir.is_absolute() else root / args.output_dir
    try:
        if args.mode == "challenge":
            run_tail_challenge(
                root,
                artifact_dir,
                output_dir=output_dir,
                generated_at=args.generated_at,
                speed=args.speed,
                max_gap_seconds=args.max_gap_seconds,
                no_sleep=args.no_sleep,
                no_play=args.no_play,
                answers=parse_challenge_answers(args.answers),
                reveal_answers=args.reveal_answers,
                stream=sys.stdout,
                input_stream=sys.stdin,
            )
        elif args.mode == "follow":
            if args.answers is not None:
                raise ExperienceError("--answers is only valid with --mode challenge")
            if args.reveal_answers:
                raise ExperienceError("--reveal-answers is only valid with --mode challenge")
            run_follow_experience(
                artifact_dir,
                output_dir=output_dir,
                generated_at=args.generated_at,
                speed=args.speed,
                max_gap_seconds=args.max_gap_seconds,
                poll_interval_seconds=args.poll_interval_seconds,
                timeout_seconds=args.follow_timeout_seconds,
                idle_timeout_seconds=args.follow_idle_timeout_seconds,
                no_play=args.no_play,
                stream=sys.stdout,
            )
        else:
            if args.answers is not None:
                raise ExperienceError("--answers is only valid with --mode challenge")
            if args.reveal_answers:
                raise ExperienceError("--reveal-answers is only valid with --mode challenge")
            run_tail_experience(
                artifact_dir,
                output_dir=output_dir,
                generated_at=args.generated_at,
                speed=args.speed,
                max_gap_seconds=args.max_gap_seconds,
                no_sleep=args.no_sleep,
                no_play=args.no_play,
                stream=sys.stdout,
            )
    except (ExperienceError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"experience error: {exc}", file=sys.stderr)
        return 2
    return 0


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
    explicit_sets = _resolve_explicit_combination_sets(root, args)
    combination_sets.extend(explicit_sets)
    source["specified"] = len(explicit_sets)
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
    try:
        random_report = _build_random_compatibility_plan_report(
            root,
            count=count,
            size=size,
            archetypes=archetypes,
            seed=seed,
            mode="real",
        )
    except ValueError as exc:
        if "planner report would enumerate" not in str(exc):
            raise
    else:
        return [
            [_resolve_cli_path(root, Path(str(path))) for path in report.get("scenario_paths", [])]
            for report in random_report["selected"]
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
        _print_json({"tools": tools})
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
        _print_json(manifest)
    else:
        print(f"release_manifest={resolved_output}")
        print(f"scenario_catalog_hash={manifest['scenario_catalog']['hash']}")
        print(f"benchmark_sets={len(manifest['benchmark_release']['benchmark_sets'])}")
        print(f"scenario_hashes={len(manifest['benchmark_release']['scenario_hashes'])}")
        print(f"artifacts={len(manifest['artifacts'])}")
    return 0


def _cmd_benchmark_sets(root: Path, *, json_output: bool) -> int:
    payload = build_benchmark_set_listing(root)
    if json_output:
        _print_json(payload)
    else:
        print(f"benchmark_sets={payload['benchmark_set_count']}\taliases={payload['alias_count']}")
        print(f"fixture_only_gate={str(payload['fixture_only_gate']).lower()}")
        print(f"requires_docker={str(payload['requires_docker']).lower()}")
    return 0


def _cmd_artifact_registry(root: Path, args: argparse.Namespace) -> int:
    if args.registry_command == "add":
        return _cmd_artifact_registry_add(root, args)
    if args.registry_command == "backfill":
        return _cmd_artifact_registry_backfill(root, args)
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
        _print_json(
            {
                "ok": True,
                "registry": str(args.registry),
                "entry_count": len(registry["entries"]),
                "entry": entry,
            }
        )
    else:
        print(f"registry={args.registry}")
        print(f"entry_count={len(registry['entries'])}")
        print(f"run_id={entry['run_id']}")
        print(f"state={entry['state']}")
        print(f"failure_class={entry['failure_class']}")
    return 0


def _cmd_artifact_registry_backfill(root: Path, args: argparse.Namespace) -> int:
    payload = backfill_registry_payload(
        root,
        manifest_path=args.manifest,
        registry_path=args.registry,
        write=args.write,
        created_at=args.created_at,
    )
    if args.json:
        _print_json(payload)
    elif payload["ok"]:
        mode = "write" if args.write else "dry-run"
        print(f"artifact-registry backfill {mode} ok\tregistry={args.registry}")
        print(f"candidate_entry_count={payload['candidate_entry_count']}")
        if args.write:
            print(f"registry_entry_count={payload.get('registry_entry_count', payload['existing_entry_count'])}")
    else:
        mode = "write" if args.write else "dry-run"
        print(f"artifact-registry backfill {mode} failed\tregistry={args.registry}")
        for finding in payload["findings"]:
            print(f"{finding['severity']}\t{finding['rule']}\t{finding.get('json_path', '')}\t{finding['message']}")
    return 0 if payload["ok"] else 2


def _cmd_artifact_registry_check(root: Path, args: argparse.Namespace) -> int:
    payload = registry_check_payload(root, registry_path=args.registry)
    _print_check_payload(payload, json_output=args.json, ok_label="artifact-registry check ok")
    return 0 if payload["ok"] else 1


def _cmd_artifact_registry_markdown(root: Path, args: argparse.Namespace) -> int:
    if args.check_output is not None:
        payload = registry_markdown_check_payload(root, registry_path=args.registry, output=args.check_output)
        if args.json:
            _print_json(payload)
        elif payload["ok"]:
            print(f"artifact-registry markdown ok\toutput={payload['output']}")
        else:
            print(f"artifact-registry markdown drift\toutput={payload['output']}")
        return 0 if payload["ok"] else 1
    if args.output is not None:
        write_registry_markdown(root, registry_path=args.registry, output=args.output)
        payload = {"ok": True, "output": str(args.output)}
        if args.json:
            _print_json(payload)
        else:
            print(f"artifact_registry_markdown={args.output}")
        return 0
    markdown = render_registry_markdown(root, registry_path=args.registry)
    if args.json:
        _print_json({"ok": True, "markdown": markdown})
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
        _print_json(payload)
        return
    if payload["ok"]:
        print(f"{ok_label}\twarnings={payload['warning_count']}")
        return
    for finding in payload["findings"]:
        location = finding["path"]
        if "line" in finding:
            location = f"{location}:{finding['line']}"
        print(f"{finding['severity']}\t{finding['rule']}\t{location}\t{finding['message']}")
