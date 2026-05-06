from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from math import comb
from pathlib import Path
from unittest import mock

from incident_generator import cli as cli_module
from incident_generator import scenario_runtime
from incident_generator.cli import _random_compatible_combination_sets
from incident_generator.checks import check_fixture_hygiene, check_markdown_links
from incident_generator.progress import OperatorProgressReporter
from incident_generator.provider_contracts import provider_contracts_by_adapter
from incident_generator.release import build_release_manifest
from incident_generator.scenario_runtime import (
    ChaosMeshPhasePredicate,
    PredicateResult,
    PostgresConnectionCountMinPredicate,
    SymptomWaiter,
    TlsCertificateInvalidPredicate,
)
from incident_generator.scenarios import (
    ArchetypeContext,
    ScenarioPackage,
    dispatch_archetype,
    list_scenario_packages,
    load_scenario_package,
    scenario_resource_claim_records,
    stand_up_combinatorial_incident_environment,
    stand_up_incident_environment,
    validate_scenario_package,
)


ROOT = Path(__file__).resolve().parents[1]


class IncidentGeneratorCliTests(unittest.TestCase):
    def run_cli(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "incident_generator", *args],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def _write_test_registry(self, root: Path) -> tuple[Path, Path]:
        artifact_dir = root / "artifacts"
        registry_path = root / "registry.json"
        _write_registry_artifacts(artifact_dir)
        result = self.run_cli(
            "artifact-registry",
            "add",
            "--registry",
            str(registry_path),
            "--artifact-dir",
            str(artifact_dir),
            "--benchmark-set-id",
            "kind-random8-20260506",
            "--run-id",
            "registry-check-run",
            "--seed",
            "20260506",
            "--host-profile",
            "kind/warm-batch",
            "--docker-host-kind",
            "ssh",
            "--docker-host",
            "ssh://JYW4HTC26N",
            "--command",
            "python3 -m incident_generator run --random-compatible-combinations 8 --json",
            "--env",
            "SECRET_TOKEN=super-secret",
            "--env",
            "SRE_AGENT_KIND_CREATE_TIMEOUT_SECONDS=600",
            "--created-at",
            "2026-05-06T00:00:00Z",
            "--json",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return registry_path, artifact_dir

    def test_list_finds_scenario_catalog(self) -> None:
        result = self.run_cli("list", "--json")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertGreaterEqual(payload["count"], 40)
        self.assertTrue(any(row["name"] == "linux-disk-full-capacity" for row in payload["scenarios"]))

    def test_validate_single_scenario(self) -> None:
        result = self.run_cli("validate", "--scenario", "scenarios/linux/disk-full/capacity", "--json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["valid"])

    def test_catalog_reports_live_readiness(self) -> None:
        result = self.run_cli("catalog", "--json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertGreaterEqual(payload["count"], 40)
        self.assertGreaterEqual(payload["by_live_readiness"].get("local-real", 0), 40)
        self.assertIn("linux.disk_usage", payload["by_evidence_adapter"])

    def test_docs_check_passes_repository_links(self) -> None:
        result = self.run_cli("docs-check", "--json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])

    def test_fixture_hygiene_passes_allowlisted_fixtures(self) -> None:
        result = self.run_cli("fixture-hygiene", "--json")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])

    def test_http_endpoint_contract_preserves_5xx_evidence(self) -> None:
        contract = provider_contracts_by_adapter()["service.endpoint_check"]

        command = contract.render_command({"url": "https://checkout.example.com/health"})

        self.assertIn("curl -sS", command)
        self.assertNotIn("curl -fsS", command)

    def test_runtime_harness_paths_exist_in_source_and_export_layouts(self) -> None:
        self.assertTrue(scenario_runtime.DNS_PROBE_LOOKUP_SCRIPT.is_file())
        self.assertTrue(scenario_runtime.TLS_TARGET_CHECK_SCRIPT.is_file())
        self.assertTrue(scenario_runtime.MESSAGING_STATE_READ_SCRIPT.is_file())

    def test_docs_check_rejects_missing_relative_link(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("[missing](docs/missing.md)\n")
            findings = check_markdown_links(root)
        self.assertTrue(any(finding.rule == "markdown-link" for finding in findings))

    def test_fixture_hygiene_rejects_unallowlisted_secret_assignment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture_dir = root / "evals/example"
            fixture_dir.mkdir(parents=True)
            (fixture_dir / "fixture.yaml").write_text("stdout: 'token=real-secret-value'\n")
            findings = check_fixture_hygiene(root)
        self.assertTrue(any(finding.rule == "raw-secret-assignment" for finding in findings))

    def test_release_manifest_records_catalog_hash_and_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp)
            artifact = artifact_dir / "incident_generator-0.1.0-py3-none-any.whl"
            artifact.write_bytes(b"wheel-bytes")
            manifest = build_release_manifest(ROOT, artifact_dir=artifact_dir)

        self.assertEqual(manifest["kind"], "ReleaseManifest")
        self.assertEqual(manifest["scenario_catalog"]["count"], 41)
        self.assertEqual(len(manifest["scenario_catalog"]["hash"]), 64)
        self.assertEqual(manifest["artifacts"][0]["sha256"], "9ceb18f15662bb87e54af2f5953c0484d2ef76f5444d87913360b9ef87d7296d")
        benchmark_release = manifest["benchmark_release"]
        self.assertEqual(benchmark_release["schema_version"], "incident-generator.benchmark-release/v1")
        self.assertEqual(len(benchmark_release["scenario_hashes"]), 41)
        disk_hash = next(
            row for row in benchmark_release["scenario_hashes"] if row["name"] == "linux-disk-full-capacity"
        )
        self.assertEqual(disk_hash["path"], "scenarios/linux/disk-full/capacity")
        self.assertEqual(disk_hash["environment_archetype"], "linux-vm")
        self.assertEqual(len(disk_hash["sha256"]), 64)
        sets = {row["benchmark_set_id"]: row for row in benchmark_release["benchmark_sets"]}
        self.assertEqual(sets["kind-random8-warm-20260506"]["seed"], 20260506)
        self.assertEqual(sets["triple-fixture-preview-20260506"]["size"], 8)
        self.assertEqual(sets["conflicting-signal-combo-fixture-20260506"]["size"], 3)
        self.assertTrue(sets["conflicting-signal-combo-fixture-20260506"]["source_hashes"])
        self.assertTrue(sets["kind-random8-warm-20260506"]["source_hashes"])
        self.assertTrue(all(row["kind"] != "missing" for row in sets["kind-random8-warm-20260506"]["source_hashes"]))
        profiles = {row["profile_id"]: row for row in benchmark_release["supported_host_profiles"]}
        self.assertEqual(profiles["kind/warm-batch"]["recommended"]["docker_disk_gib"], 30)
        self.assertFalse(benchmark_release["runtime_assumptions"]["fixture_mode_requires_docker"])
        self.assertIn("kind", benchmark_release["runtime_assumptions"]["real_mode_required_tools"])
        self.assertTrue(
            any("no standalone runner command emits result payloads" in value for value in benchmark_release["known_limitations"])
        )

    def test_artifact_registry_add_appends_hashed_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact_dir = root / "artifacts"
            replay_dir = root / "validated-combo-agents"
            registry_path = root / "registry.json"
            replay_path = replay_dir / "summary.json"
            result_payload = _write_registry_artifacts(artifact_dir)
            replay_dir.mkdir(parents=True)
            replay_path.write_text(
                json.dumps(
                    {
                        "schema_version": "sre-agent.validated-combo-agent-batch/v1",
                        "agent": "deterministic",
                        "passed": True,
                        "passed_count": 1,
                        "count": 1,
                    },
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            result = self.run_cli(
                "artifact-registry",
                "add",
                "--registry",
                str(registry_path),
                "--artifact-dir",
                str(artifact_dir),
                "--benchmark-set-id",
                "kind-random8-20260506",
                "--run-id",
                "20260506-kind-random8-01",
                "--seed",
                "20260506",
                "--host-profile",
                "kind/warm-batch",
                "--docker-host-kind",
                "ssh",
                "--docker-host",
                "ssh://JYW4HTC26N",
                "--architecture",
                "x86_64",
                "--cpu-count",
                "8",
                "--memory-bytes",
                "17179869184",
                "--docker-data-root-free-bytes",
                "32212254720",
                "--command",
                "python3 -m incident_generator run --random-compatible-combinations 8 --json",
                "--env",
                "SECRET_TOKEN=super-secret",
                "--env",
                "SRE_AGENT_KIND_CREATE_TIMEOUT_SECONDS=600",
                "--agent-replay-summary",
                str(replay_path),
                "--created-at",
                "2026-05-06T00:00:00Z",
                "--json",
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            entry = registry["entries"][0]
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["entry_count"], 1)
            self.assertEqual(entry["run_id"], "20260506-kind-random8-01")
            self.assertEqual(entry["benchmark_set_id"], "kind-random8-20260506")
            self.assertEqual(entry["seed"], 20260506)
            self.assertEqual(entry["scenario_ids"], [scenario["name"] for scenario in result_payload["runs"][0]["scenarios"]])
            self.assertEqual(entry["combination_size"], 2)
            self.assertEqual(entry["archetype"], "kind")
            self.assertEqual(entry["collection_mode"], "real")
            self.assertEqual(entry["state"], "passed")
            self.assertEqual(entry["failure_class"], "none")
            self.assertEqual(entry["host_profile"]["profile_id"], "kind/warm-batch")
            self.assertEqual(entry["host_profile"]["docker_host_kind"], "ssh")
            self.assertEqual(entry["command"]["env"]["SECRET_TOKEN"], "[redacted]")
            self.assertEqual(entry["command"]["env"]["SRE_AGENT_KIND_CREATE_TIMEOUT_SECONDS"], "600")
            self.assertEqual(entry["environment_fingerprint"]["timeout_overrides"], {"SRE_AGENT_KIND_CREATE_TIMEOUT_SECONDS": "600"})
            self.assertEqual(entry["retained_paths"]["result_json"], "artifacts/result.json")
            self.assertEqual(entry["retained_paths"]["events_ndjson"], "artifacts/events.ndjson")
            self.assertEqual(entry["retained_paths"]["summary_json"], "artifacts/summary.json")
            self.assertEqual(entry["retained_paths"]["dashboard_json"], "artifacts/dashboard.json")
            self.assertEqual(entry["retained_paths"]["agent_replay_summary_json"], "validated-combo-agents/summary.json")
            self.assertEqual(entry["content_hashes"]["result_json"]["value"], _sha256_file(artifact_dir / "result.json"))
            self.assertEqual(entry["content_hashes"]["events_ndjson"]["value"], _sha256_file(artifact_dir / "events.ndjson"))
            self.assertEqual(entry["agent_replay"]["passed"], True)

    def test_artifact_registry_add_rejects_missing_required_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact_dir = root / "artifacts"
            registry_path = root / "registry.json"
            _write_registry_artifacts(artifact_dir)
            (artifact_dir / "events.ndjson").unlink()

            result = self.run_cli(
                "artifact-registry",
                "add",
                "--registry",
                str(registry_path),
                "--artifact-dir",
                str(artifact_dir),
                "--benchmark-set-id",
                "kind-random8-20260506",
                "--command",
                "python3 -m incident_generator run --json",
            )

            self.assertEqual(result.returncode, 2)
            self.assertIn("required artifact is missing", result.stderr)
            self.assertFalse(registry_path.exists())

    def test_artifact_registry_add_rejects_duplicate_run_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            artifact_dir = root / "artifacts"
            registry_path = root / "registry.json"
            _write_registry_artifacts(artifact_dir)
            args = [
                "artifact-registry",
                "add",
                "--registry",
                str(registry_path),
                "--artifact-dir",
                str(artifact_dir),
                "--benchmark-set-id",
                "kind-random8-20260506",
                "--run-id",
                "duplicate-run",
                "--command",
                "python3 -m incident_generator run --json",
            ]

            first = self.run_cli(*args)
            second = self.run_cli(*args)

            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            self.assertEqual(second.returncode, 2)
            self.assertIn("registry already contains run_id: duplicate-run", second.stderr)

    def test_artifact_registry_check_accepts_generated_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry_path, _artifact_dir = self._write_test_registry(Path(tmp))

            result = self.run_cli("artifact-registry", "check", "--registry", str(registry_path), "--json")

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout)
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["entry_count"], 1)
            self.assertEqual(payload["error_count"], 0)

    def test_artifact_registry_check_rejects_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry_path, artifact_dir = self._write_test_registry(Path(tmp))
            (artifact_dir / "result.json").write_text('{"changed": true}\n', encoding="utf-8")

            result = self.run_cli("artifact-registry", "check", "--registry", str(registry_path), "--json")

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"])
            self.assertIn("artifact-hash", {finding["rule"] for finding in payload["findings"]})

    def test_artifact_registry_check_rejects_missing_retained_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry_path, artifact_dir = self._write_test_registry(Path(tmp))
            (artifact_dir / "summary.json").unlink()

            result = self.run_cli("artifact-registry", "check", "--registry", str(registry_path), "--json")

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            self.assertFalse(payload["ok"])
            self.assertIn("artifact-missing", {finding["rule"] for finding in payload["findings"]})

    def test_artifact_registry_check_rejects_unsafe_path_and_unredacted_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            registry_path, _artifact_dir = self._write_test_registry(Path(tmp))
            registry = json.loads(registry_path.read_text(encoding="utf-8"))
            entry = registry["entries"][0]
            entry["retained_paths"]["result_json"] = "/tmp/result.json"
            entry["command"]["env"]["SECRET_TOKEN"] = "super-secret"
            registry_path.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n", encoding="utf-8")

            result = self.run_cli("artifact-registry", "check", "--registry", str(registry_path), "--json")

            self.assertEqual(result.returncode, 1)
            payload = json.loads(result.stdout)
            rules = {finding["rule"] for finding in payload["findings"]}
            self.assertIn("unsafe-path", rules)
            self.assertIn("unredacted-env", rules)

    def test_artifact_registry_markdown_writes_and_checks_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            registry_path, _artifact_dir = self._write_test_registry(root)
            report_path = root / "artifact-registry.md"

            write_result = self.run_cli(
                "artifact-registry",
                "markdown",
                "--registry",
                str(registry_path),
                "--output",
                str(report_path),
                "--json",
            )
            check_result = self.run_cli(
                "artifact-registry",
                "markdown",
                "--registry",
                str(registry_path),
                "--check-output",
                str(report_path),
                "--json",
            )
            report_path.write_text(report_path.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            drift_result = self.run_cli(
                "artifact-registry",
                "markdown",
                "--registry",
                str(registry_path),
                "--check-output",
                str(report_path),
                "--json",
            )

            self.assertEqual(write_result.returncode, 0, write_result.stdout + write_result.stderr)
            self.assertIn("| registry-check-run | kind-random8-20260506 |", report_path.read_text(encoding="utf-8"))
            self.assertEqual(check_result.returncode, 0, check_result.stdout + check_result.stderr)
            self.assertTrue(json.loads(check_result.stdout)["ok"])
            self.assertEqual(drift_result.returncode, 1)
            self.assertFalse(json.loads(drift_result.stdout)["ok"])

    def test_validate_rejects_unknown_wait_predicate(self) -> None:
        package = load_scenario_package(ROOT / "scenarios/linux/disk-full/capacity")
        expect = copy.deepcopy(package.expect)
        expect["wait_for"]["predicates"][0]["kind"] = "not_a_predicate"
        invalid = ScenarioPackage(path=package.path, spec=package.spec, expect=expect)
        failures = validate_scenario_package(invalid)
        self.assertTrue(any("not_a_predicate" in failure for failure in failures))

    def test_validate_rejects_missing_fixture_output_reference(self) -> None:
        package = load_scenario_package(ROOT / "scenarios/linux/disk-full/capacity")
        spec = copy.deepcopy(package.spec)
        spec["evidence_adapters_required"].append("service.endpoint_check")
        invalid = ScenarioPackage(path=package.path, spec=spec, expect=package.expect)
        failures = validate_scenario_package(invalid)
        self.assertTrue(any("fixture output is missing for service.endpoint_check" in failure for failure in failures))

    def test_validate_rejects_malformed_resource_conflicts(self) -> None:
        package = load_scenario_package(ROOT / "scenarios/linux/disk-full/capacity")
        spec = copy.deepcopy(package.spec)
        spec["resource_claims"][0]["conflicts_with"] = "linux.evidenceFile/app-host/var-sre-agent-oom-events.log"
        invalid = ScenarioPackage(path=package.path, spec=spec, expect=package.expect)
        failures = validate_scenario_package(invalid)

        self.assertTrue(any("resource_claims[0].conflicts_with must be a list" in failure for failure in failures))

    def test_kind_scenarios_declare_real_resource_claims(self) -> None:
        packages = [
            load_scenario_package(path)
            for path in list_scenario_packages(ROOT)
            if load_scenario_package(path).spec.get("environment_archetype") == "kind"
        ]
        missing = [package.name for package in packages if not scenario_resource_claim_records([package], mode="real")]
        resources = {record["resource"] for record in scenario_resource_claim_records(packages, mode="real")}

        self.assertEqual(len(packages), 32)
        self.assertEqual(missing, [])
        self.assertIn("kubernetes.ConfigMap/kube-system/coredns", resources)
        self.assertIn("kubernetes.Deployment/payments/checkout-api", resources)
        self.assertIn("kubernetes.NodeLabel/sre-agent.io/node-pressure", resources)
        self.assertIn("kubernetes.ConfigMap/orders/sre-agent-messaging-evidence", resources)

    def test_validate_accepts_workload_profile_and_incident_injection(self) -> None:
        package = load_scenario_package(ROOT / "scenarios/linux/disk-full/capacity")
        spec = copy.deepcopy(package.spec)
        spec["workload_profile"] = _valid_workload_profile()
        spec["incident_injection"] = _valid_incident_injection("disk_capacity")
        with_workload = ScenarioPackage(path=package.path, spec=spec, expect=package.expect)

        self.assertEqual(validate_scenario_package(with_workload), [])

    def test_validate_rejects_malformed_workload_profile(self) -> None:
        package = load_scenario_package(ROOT / "scenarios/linux/disk-full/capacity")
        spec = copy.deepcopy(package.spec)
        spec["workload_profile"] = _valid_workload_profile()
        del spec["workload_profile"]["load_generator"]["traffic_mix"]
        spec["workload_profile"]["load_generator"]["concurrency"] = 0
        invalid = ScenarioPackage(path=package.path, spec=spec, expect=package.expect)

        failures = validate_scenario_package(invalid)

        self.assertIn("workload_profile.load_generator.traffic_mix is required", failures)
        self.assertIn("workload_profile.load_generator.concurrency must be a positive integer", failures)

    def test_validate_rejects_incident_injection_hypothesis_mismatch(self) -> None:
        package = load_scenario_package(ROOT / "scenarios/linux/disk-full/capacity")
        spec = copy.deepcopy(package.spec)
        spec["incident_injection"] = _valid_incident_injection("network_partition")
        invalid = ScenarioPackage(path=package.path, spec=spec, expect=package.expect)

        failures = validate_scenario_package(invalid)

        self.assertIn("incident_injection.expected_hypothesis must match one of expected_hypotheses", failures)

    def test_real_run_reports_teardown_verification_failures(self) -> None:
        package = load_scenario_package(ROOT / "scenarios/linux/disk-full/capacity")
        teardown_calls: list[str] = []

        def dispatch(*_args: object, **_kwargs: object) -> ArchetypeContext:
            return ArchetypeContext(
                archetype="linux-vm",
                host_env={},
                teardown=lambda: teardown_calls.append("teardown"),
                teardown_verifier=lambda: [{"check": "linux_vm_volumes_removed", "error": "compose volumes still exist"}],
            )

        result = stand_up_incident_environment(
            package,
            collection_mode="real",
            require_tools=True,
            dispatch_archetype_func=dispatch,
            seed_executor=_SuccessfulSeedExecutor(),
            symptom_waiter=_SuccessfulWaiter(),
            resolve_selectors_func=lambda *_args, **_kwargs: _SelectorResult(),
            start_port_forwards_func=lambda *_args, **_kwargs: _PortForwardRun(),
        )

        self.assertFalse(result["blocked"])
        self.assertEqual(result["failure_class"], "adapter_runtime_issue")
        self.assertTrue(result["failure_classification"]["retriable"])
        self.assertEqual(teardown_calls, ["teardown"])
        self.assertFalse(result["context"]["teardown"]["verified"])
        self.assertEqual(result["teardown_failures"][0]["check"], "linux_vm_volumes_removed")

    def test_kind_teardown_verifier_detects_leftover_cluster_and_kubeconfig(self) -> None:
        package = load_scenario_package(ROOT / "scenarios/kubernetes/pending-pod/unschedulable")

        def runner(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            if args[:3] == ["kind", "get", "clusters"]:
                return subprocess.CompletedProcess(args, 0, stdout="sre-agent-phase-a\n", stderr="")
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        ctx = dispatch_archetype(
            "kind",
            package=package,
            workdir=ROOT,
            tool_lookup=lambda _tool: "/usr/bin/tool",
            command_runner=runner,
        )
        try:
            failures = ctx.teardown_verifier()
        finally:
            if ctx.kubeconfig_path is not None:
                Path(ctx.kubeconfig_path).unlink(missing_ok=True)

        self.assertTrue(any(failure["check"] == "kind_cluster_deleted" for failure in failures))
        self.assertTrue(any(failure["check"] == "kind_kubeconfig_removed" for failure in failures))

    def test_kind_teardown_verifier_allows_warm_retained_cluster(self) -> None:
        package = load_scenario_package(ROOT / "scenarios/kubernetes/pending-pod/unschedulable")

        def runner(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            if args[:3] == ["kind", "get", "clusters"]:
                return subprocess.CompletedProcess(args, 0, stdout="sre-agent-phase-a\n", stderr="")
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        ctx = dispatch_archetype(
            "kind",
            package=package,
            workdir=ROOT,
            host_env={"SRE_AGENT_KIND_KEEP_CLUSTER": "1"},
            tool_lookup=lambda _tool: "/usr/bin/tool",
            command_runner=runner,
        )
        try:
            failures = ctx.teardown_verifier()
        finally:
            if ctx.kubeconfig_path is not None:
                Path(ctx.kubeconfig_path).unlink(missing_ok=True)

        self.assertFalse(any(failure["check"] == "kind_cluster_deleted" for failure in failures))
        self.assertTrue(any(failure["check"] == "kind_kubeconfig_removed" for failure in failures))

    def test_linux_vm_teardown_verifier_detects_leftover_compose_resources(self) -> None:
        package = load_scenario_package(ROOT / "scenarios/linux/disk-full/capacity")

        def runner(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            if args[:3] == ["docker", "compose", "version"]:
                return subprocess.CompletedProcess(args, 0, stdout="Docker Compose version v2.27.0", stderr="")
            if args[:3] == ["docker", "compose", "-f"] and args[-2:] == ["ps", "-q"]:
                return subprocess.CompletedProcess(args, 0, stdout="container-id\n", stderr="")
            if args[:3] == ["docker", "volume", "ls"]:
                return subprocess.CompletedProcess(args, 0, stdout="volume-id\n", stderr="")
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")

        ctx = dispatch_archetype(
            "linux-vm",
            package=package,
            workdir=ROOT,
            tool_lookup=lambda _tool: "/usr/bin/tool",
            command_runner=runner,
        )

        failures = ctx.teardown_verifier()

        self.assertTrue(any(failure["check"] == "linux_vm_compose_stopped" for failure in failures))
        self.assertTrue(any(failure["check"] == "linux_vm_volumes_removed" for failure in failures))

    def test_eks_staging_is_blocked_before_terraform_dispatch(self) -> None:
        package = load_scenario_package(ROOT / "scenarios/linux/disk-full/capacity")
        spec = copy.deepcopy(package.spec)
        spec["environment_archetype"] = "eks-staging"
        invalid = ScenarioPackage(path=package.path, spec=spec, expect=package.expect)

        result = stand_up_incident_environment(invalid, collection_mode="real", require_tools=True, workdir=ROOT)

        self.assertTrue(result["blocked"])
        self.assertEqual(result["failure_class"], "adapter_runtime_issue")
        self.assertTrue(any("eks-staging" in reason for reason in result["blocking_reasons"]))

    def test_failure_classifier_marks_runtime_preconditions_retriable(self) -> None:
        package = load_scenario_package(ROOT / "scenarios/linux/disk-full/capacity")

        def dispatch(*_args: object, **_kwargs: object) -> ArchetypeContext:
            return ArchetypeContext(
                archetype="linux-vm",
                host_env={},
                precondition_failures=[{"check": "docker_compose", "error": "docker daemon timeout"}],
            )

        result = stand_up_incident_environment(
            package,
            collection_mode="real",
            require_tools=True,
            dispatch_archetype_func=dispatch,
            workdir=ROOT,
        )

        self.assertTrue(result["blocked"])
        self.assertEqual(result["failure_class"], "adapter_runtime_issue")
        self.assertTrue(result["failure_classification"]["retriable"])

    def test_failure_classifier_marks_seed_failures_separately(self) -> None:
        package = load_scenario_package(ROOT / "scenarios/linux/disk-full/capacity")

        def dispatch(*_args: object, **_kwargs: object) -> ArchetypeContext:
            return ArchetypeContext(archetype="linux-vm", host_env={})

        result = stand_up_incident_environment(
            package,
            collection_mode="real",
            require_tools=True,
            dispatch_archetype_func=dispatch,
            seed_executor=_FailingSeedExecutor("seed_sh", "seed failed"),
            symptom_waiter=_SuccessfulWaiter(),
            resolve_selectors_func=lambda *_args, **_kwargs: _SelectorResult(),
            start_port_forwards_func=lambda *_args, **_kwargs: _PortForwardRun(),
            workdir=ROOT,
        )

        self.assertTrue(result["blocked"])
        self.assertEqual(result["failure_class"], "seed_predicate_runtime_issue")
        self.assertFalse(result["failure_classification"]["retriable"])
        self.assertEqual(result["failure_classification"]["signals"][0]["source"], "seed_failures")

    def test_failure_classifier_marks_wait_predicate_failures_separately(self) -> None:
        package = load_scenario_package(ROOT / "scenarios/linux/disk-full/capacity")

        def dispatch(*_args: object, **_kwargs: object) -> ArchetypeContext:
            return ArchetypeContext(archetype="linux-vm", host_env={})

        result = stand_up_incident_environment(
            package,
            collection_mode="real",
            require_tools=True,
            dispatch_archetype_func=dispatch,
            seed_executor=_SuccessfulSeedExecutor(),
            symptom_waiter=_FailingWaiter("disk_usage", "predicate timeout"),
            resolve_selectors_func=lambda *_args, **_kwargs: _SelectorResult(),
            start_port_forwards_func=lambda *_args, **_kwargs: _PortForwardRun(),
            workdir=ROOT,
        )

        self.assertTrue(result["blocked"])
        self.assertEqual(result["failure_class"], "seed_predicate_runtime_issue")
        self.assertEqual(result["failure_classification"]["signals"][0]["source"], "wait_for_failures")

    def test_fixture_run_is_deterministic_and_does_not_start_infra(self) -> None:
        result = self.run_cli(
            "run",
            "--scenario",
            "scenarios/linux/disk-full/capacity",
            "--collection-mode",
            "fixture",
            "--json",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["generated"])
        self.assertTrue(payload["deterministic"])
        self.assertEqual(payload["environment_archetype"], "fixture")
        self.assertEqual(payload["failure_class"], "none")

    def test_fixture_combination_run_bundles_multiple_failure_modes(self) -> None:
        result = self.run_cli(
            "run",
            "--scenario",
            "scenarios/linux/disk-full/capacity",
            "--scenario",
            "scenarios/linux/memory-oom/oom-kill",
            "--collection-mode",
            "fixture",
            "--variant",
            "filesystem=ext4",
            "--json",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["combined"])
        self.assertTrue(payload["generated"])
        self.assertEqual(payload["scenario_count"], 2)
        self.assertEqual(payload["collection_mode"], "fixture")
        self.assertEqual(payload["environment_archetype"], "fixture")
        self.assertEqual(len(payload["fixtures"]), 2)
        self.assertIn("linux.disk_usage", payload["evidence_adapters_required"])
        self.assertIn("linux.memory_summary", payload["evidence_adapters_required"])
        self.assertEqual(payload["variant_sets"]["linux-disk-full-capacity"]["filesystem"], "ext4")
        self.assertNotIn("filesystem", payload["variant_sets"]["linux-memory-oom-oom-kill"])

    def test_explicit_combination_flag_runs_specified_batch(self) -> None:
        result = self.run_cli(
            "run",
            "--combination",
            "scenarios/linux/disk-full/capacity,scenarios/linux/memory-oom/oom-kill",
            "--combination",
            "scenarios/service/http-5xx-spike/dependency,scenarios/service/latency-spike/downstream-db",
            "--collection-mode",
            "fixture",
            "--json",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["batch"])
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["generated_count"], 2)
        self.assertEqual(payload["combination_source"]["specified"], 2)
        self.assertTrue(all(run["combined"] for run in payload["runs"]))
        self.assertEqual(payload["runs"][0]["scenario_count"], 2)
        self.assertEqual(payload["runs"][1]["scenario_count"], 2)

    def test_explicit_combination_defaults_to_real_mode(self) -> None:
        result = self.run_cli(
            "run",
            "--combination",
            "scenarios/linux/disk-full/capacity,scenarios/service/http-5xx-spike/dependency",
            "--json",
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        payload = json.loads(result.stdout)

        self.assertEqual(payload["collection_mode"], "real")
        self.assertTrue(payload["blocked"])
        self.assertEqual(payload["failure_class"], "resource_collision")
        self.assertTrue(any("same environment_archetype" in reason for reason in payload["blocking_reasons"]))

    def test_warm_kind_rejects_non_kind_batches(self) -> None:
        result = self.run_cli(
            "run",
            "--combination",
            "scenarios/linux/disk-full/capacity,scenarios/linux/memory-oom/hot-process",
            "--combination",
            "scenarios/linux/cpu-saturation/hot-process,scenarios/linux/disk-full/inode-capacity",
            "--warm-kind",
            "--json",
        )

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("--warm-kind only supports kind scenarios", result.stderr)

    def test_warm_kind_rejects_fixture_mode(self) -> None:
        result = self.run_cli(
            "run",
            "--combination",
            "scenarios/kubernetes/pending-pod/unschedulable,scenarios/service/http-5xx-spike/canary-rollout",
            "--combination",
            "scenarios/database/connection-exhaustion/pool-exhausted,scenarios/network/path-degradation/cross-az",
            "--collection-mode",
            "fixture",
            "--warm-kind",
            "--json",
        )

        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("--warm-kind requires real collection mode", result.stderr)

    def test_random_compatible_combinations_select_same_archetype_sets(self) -> None:
        result = self.run_cli(
            "run",
            "--random-compatible-combinations",
            "2",
            "--random-combination-size",
            "2",
            "--collection-mode",
            "fixture",
            "--json",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)

        self.assertTrue(payload["batch"])
        self.assertEqual(payload["count"], 2)
        self.assertEqual(payload["combination_source"]["random"], 2)
        self.assertEqual(payload["combination_source"]["random_combination_size"], 2)
        for run in payload["runs"]:
            archetypes = {scenario["environment_archetype"] for scenario in run["scenarios"]}
            self.assertEqual(len(archetypes), 1)

    def test_random_compatible_combinations_can_be_seeded_and_archetype_scoped(self) -> None:
        args = (
            "run",
            "--random-compatible-combinations",
            "3",
            "--random-combination-size",
            "2",
            "--random-archetype",
            "linux-vm",
            "--random-seed",
            "20260505",
            "--collection-mode",
            "fixture",
            "--json",
        )
        first = self.run_cli(*args)
        second = self.run_cli(*args)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)

        first_payload = json.loads(first.stdout)
        second_payload = json.loads(second.stdout)
        first_combinations = [[scenario["name"] for scenario in run["scenarios"]] for run in first_payload["runs"]]
        second_combinations = [[scenario["name"] for scenario in run["scenarios"]] for run in second_payload["runs"]]

        self.assertEqual(first_combinations, second_combinations)
        self.assertEqual(first_payload["combination_source"]["random_archetypes"], ["linux-vm"])
        self.assertEqual(first_payload["combination_source"]["random_seed"], 20260505)
        for run in first_payload["runs"]:
            archetypes = {scenario["environment_archetype"] for scenario in run["scenarios"]}
            self.assertEqual(archetypes, {"linux-vm"})

    def test_random_compatible_combinations_match_seeded_planner_preview(self) -> None:
        plan = self.run_cli(
            "plan",
            "--random-compatible-combinations",
            "8",
            "--random-combination-size",
            "2",
            "--random-archetype",
            "kind",
            "--random-seed",
            "20260506",
            "--json",
        )
        self.assertEqual(plan.returncode, 0, plan.stdout + plan.stderr)
        planned = json.loads(plan.stdout)["random"]["selected"]

        combinations = _random_compatible_combination_sets(
            ROOT,
            count=8,
            size=2,
            archetypes=["kind"],
            seed=20260506,
        )
        combination_ids = [[load_scenario_package(path).name for path in paths] for paths in combinations]

        self.assertEqual(combination_ids, [row["scenario_names"] for row in planned])

    def test_plan_reports_explicit_resource_conflict(self) -> None:
        result = self.run_cli(
            "plan",
            "--combination",
            "scenarios/service/certificate-rotation-readiness/expiring,"
            "scenarios/service/certificate-rotation-readiness/hostname-mismatch",
            "--json",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        combination = payload["explicit"]["combinations"][0]

        self.assertEqual(payload["kind"], "CombinationPlannerReport")
        self.assertIsNone(payload["random"])
        self.assertFalse(combination["compatible"])
        self.assertEqual(combination["decision"], "rejected")
        self.assertTrue(
            any(reason["code"] == "shared_exclusive_resource" for reason in combination["reason_details"])
        )
        claimed_resources = {claim["resource"] for claim in combination["resource_claims"]}
        self.assertIn("kubernetes.Secret/edge/edge-api-tls", claimed_resources)
        self.assertIn("kubernetes.ConfigMap/kube-system/coredns", claimed_resources)
        self.assertTrue(
            any(
                conflict["type"] == "shared_exclusive_resource"
                and conflict["resource"] == "kubernetes.Secret/edge/edge-api-tls"
                for conflict in combination["target_state_conflicts"]
            )
        )
        self.assertTrue(
            any(
                conflict["type"] == "shared_exclusive_resource"
                and conflict["resource"] == "kubernetes.ConfigMap/kube-system/coredns"
                for conflict in combination["target_state_conflicts"]
            )
        )

    def test_plan_reports_random_pool_rejections_and_selected_pairs(self) -> None:
        result = self.run_cli(
            "plan",
            "--random-compatible-combinations",
            "3",
            "--random-combination-size",
            "2",
            "--random-archetype",
            "linux-vm",
            "--random-seed",
            "20260505",
            "--json",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        random_report = payload["random"]

        self.assertEqual(random_report["selected_count"], 3)
        self.assertEqual(random_report["eligible_count"], 23)
        self.assertEqual(random_report["rejected_count"], 13)
        self.assertEqual(random_report["candidate_pool"]["count"], 36)
        self.assertEqual(payload["summary"]["selected_count"], 3)
        self.assertTrue(all(item["compatible"] for item in random_report["selected"]))
        self.assertEqual({group["archetype"] for group in random_report["groups"]}, {"linux-vm"})
        self.assertTrue(
            any(
                conflict["type"] == "declared_resource_conflict"
                for item in random_report["rejected"]
                for conflict in item["target_state_conflicts"]
            )
        )

    def test_plan_reports_beyond_pairwise_resource_aggregation(self) -> None:
        result = self.run_cli(
            "plan",
            "--combination",
            "scenarios/service/certificate-rotation-readiness/expiring,"
            "scenarios/service/certificate-rotation-readiness/hostname-mismatch,"
            "scenarios/service/http-5xx-spike/canary-rollout",
            "--json",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        combination = payload["explicit"]["combinations"][0]

        self.assertFalse(combination["compatible"])
        self.assertEqual(combination["scenario_count"], 3)
        self.assertTrue(combination["beyond_pairwise"])
        self.assertEqual(combination["resource_claim_summary"]["conflict_count"], 4)
        self.assertEqual(combination["resource_claim_summary"]["shared_resource_count"], 4)
        aggregates = {row["resource"]: row for row in combination["resource_claim_aggregate"]}
        self.assertEqual(aggregates["kubernetes.Secret/edge/edge-api-tls"]["conflict_types"], ["shared_exclusive_resource"])
        self.assertEqual(aggregates["kubernetes.ConfigMap/kube-system/coredns"]["conflict_types"], ["shared_exclusive_resource"])
        self.assertEqual(len(combination["expected_hypotheses"]), 3)
        blocked_by_scenario = {
            row["scenario"]: row["codes"]
            for row in combination["scenario_incompatibilities"]
            if row["blocked"]
        }
        self.assertEqual(
            set(blocked_by_scenario),
            {
                "service-certificate-rotation-readiness-expiring",
                "service-certificate-rotation-readiness-hostname-mismatch",
            },
        )
        self.assertTrue(all("shared_exclusive_resource" in codes for codes in blocked_by_scenario.values()))

    def test_plan_renders_seeded_fixture_mode_triple_preview(self) -> None:
        args = (
            "plan",
            "--collection-mode",
            "fixture",
            "--random-compatible-combinations",
            "2",
            "--random-combination-size",
            "3",
            "--random-archetype",
            "linux-vm",
            "--random-seed",
            "20260506",
            "--json",
        )
        first = self.run_cli(*args)
        second = self.run_cli(*args)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)

        first_payload = json.loads(first.stdout)
        second_payload = json.loads(second.stdout)
        random_report = first_payload["random"]
        self.assertEqual(random_report["compatibility_mode"], "fixture")
        self.assertTrue(random_report["deterministic"])
        self.assertEqual(random_report["selected_count"], 2)
        self.assertEqual(random_report["candidate_pool"]["combination_size"], 3)
        self.assertEqual(random_report["candidate_pool"]["count"], comb(random_report["groups"][0]["scenario_count"], 3))
        self.assertEqual(
            [row["scenario_paths"] for row in random_report["selected"]],
            [row["scenario_paths"] for row in second_payload["random"]["selected"]],
        )
        for row in random_report["selected"]:
            self.assertTrue(row["compatible"], row["reason_details"])
            self.assertTrue(row["beyond_pairwise"])
            self.assertEqual(row["scenario_count"], 3)
            self.assertEqual(len(row["expected_hypotheses"]), 3)

    def test_real_combination_reuses_one_archetype_and_tears_down_each_seed(self) -> None:
        packages = [
            load_scenario_package(ROOT / "scenarios/linux/disk-full/capacity"),
            load_scenario_package(ROOT / "scenarios/linux/memory-oom/hot-process"),
        ]
        events: list[tuple[str, str]] = []

        def dispatch(archetype: str, *, package: ScenarioPackage, workdir: Path) -> ArchetypeContext:
            del package, workdir
            events.append(("dispatch", archetype))
            return ArchetypeContext(
                archetype=archetype,
                host_env={},
                teardown=lambda: events.append(("archetype-teardown", archetype)),
                teardown_verifier=lambda: [],
            )

        result = stand_up_combinatorial_incident_environment(
            packages,
            collection_mode="real",
            require_tools=True,
            dispatch_archetype_func=dispatch,
            seed_executor=_RecordingSeedExecutor(events),
            symptom_waiter=_RecordingWaiter(events),
            resolve_selectors_func=lambda package, *_args, **_kwargs: _RecordingSelectorResult(package, events),
            start_port_forwards_func=lambda *_args, **_kwargs: _PortForwardRun(),
        )

        self.assertFalse(result["blocked"])
        self.assertTrue(result["combined"])
        self.assertEqual(result["failure_class"], "none")
        self.assertEqual(result["environment_archetype"], "linux-vm")
        self.assertEqual(result["context"]["seed_results"], [
            {"scenario": "linux-disk-full-capacity", "applied": True},
            {"scenario": "linux-memory-oom-hot-process", "applied": True},
        ])
        self.assertIn(("dispatch", "linux-vm"), events)
        self.assertLess(
            events.index(("teardown", "linux-memory-oom-hot-process")),
            events.index(("teardown", "linux-disk-full-capacity")),
        )
        self.assertEqual(events[-1], ("archetype-teardown", "linux-vm"))

    def test_warm_kind_batch_sets_reuse_env_and_runs_final_cleanup(self) -> None:
        previous = {key: os.environ.get(key) for key in cli_module.WARM_KIND_ENV}
        for key in cli_module.WARM_KIND_ENV:
            os.environ.pop(key, None)
        args = argparse.Namespace(
            incident_session_id="warm-kind-test",
            incident_id=None,
            require_tools=True,
            warm_kind=True,
        )
        combination_sets = [
            [
                ROOT / "scenarios/kubernetes/pending-pod/unschedulable",
                ROOT / "scenarios/service/http-5xx-spike/canary-rollout",
            ],
            [
                ROOT / "scenarios/database/connection-exhaustion/pool-exhausted",
                ROOT / "scenarios/network/path-degradation/cross-az",
            ],
        ]
        observed_env: list[dict[str, str | None]] = []
        commands: list[list[str]] = []

        def fake_run_one(*_args: object, **kwargs: object) -> dict[str, object]:
            observed_env.append({key: os.environ.get(key) for key in cli_module.WARM_KIND_ENV})
            return {
                "blocked": False,
                "generated": True,
                "combined": True,
                "scenario": f"batch-{kwargs.get('batch_index')}",
                "collection_mode": "real",
            }

        def fake_subprocess_run(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            commands.append(args)
            if args[:3] == ["kind", "get", "clusters"]:
                return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
            return subprocess.CompletedProcess(args, 0, stdout="deleted\n", stderr="")

        try:
            with mock.patch.object(cli_module, "_run_one_combination", side_effect=fake_run_one):
                with mock.patch.object(cli_module.subprocess, "run", side_effect=fake_subprocess_run):
                    result = cli_module._run_combination_batch(
                        ROOT,
                        args,
                        combination_sets,
                        variants={},
                        collection_mode="real",
                        hold_seconds=None,
                        progress_reporter=None,
                        source={
                            "specified": 2,
                            "random": 0,
                            "random_combination_size": 2,
                            "random_archetypes": [],
                            "random_seed": None,
                        },
                    )
        finally:
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value

        self.assertFalse(result["blocked"])
        self.assertEqual(result["failure_class"], "none")
        self.assertTrue(result["warm_kind"]["cleanup"]["verified"])
        self.assertEqual(
            observed_env,
            [
                {"SRE_AGENT_KIND_KEEP_CLUSTER": "1", "SRE_AGENT_OBSERVABILITY_REUSE_READY": "1"},
                {"SRE_AGENT_KIND_KEEP_CLUSTER": "1", "SRE_AGENT_OBSERVABILITY_REUSE_READY": "1"},
            ],
        )
        self.assertEqual(os.environ.get("SRE_AGENT_KIND_KEEP_CLUSTER"), previous["SRE_AGENT_KIND_KEEP_CLUSTER"])
        self.assertTrue(any(str(command[0]).endswith("harness/archetypes/kind/down.sh") for command in commands))
        self.assertIn(["kind", "get", "clusters"], commands)

    def test_real_combination_rejects_mixed_archetypes(self) -> None:
        result = stand_up_combinatorial_incident_environment(
            [
                load_scenario_package(ROOT / "scenarios/linux/disk-full/capacity"),
                load_scenario_package(ROOT / "scenarios/service/http-5xx-spike/dependency"),
            ],
            collection_mode="real",
            require_tools=True,
        )

        self.assertTrue(result["blocked"])
        self.assertTrue(any("same environment_archetype" in reason for reason in result["blocking_reasons"]))

    def test_real_combination_rejects_shared_exclusive_resource(self) -> None:
        result = self.run_cli(
            "run",
            "--combination",
            "scenarios/service/certificate-rotation-readiness/expiring,"
            "scenarios/service/certificate-rotation-readiness/hostname-mismatch",
            "--json",
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        payload = json.loads(result.stdout)

        self.assertEqual(payload["collection_mode"], "real")
        self.assertTrue(payload["blocked"])
        self.assertEqual(payload["failure_class"], "resource_collision")
        self.assertTrue(
            any(
                "scenarios share resource kubernetes.Secret/edge/edge-api-tls" in reason
                for reason in payload["blocking_reasons"]
            )
        )

    def test_fixture_combination_allows_shared_real_resource_claims(self) -> None:
        result = self.run_cli(
            "run",
            "--combination",
            "scenarios/service/certificate-rotation-readiness/expiring,"
            "scenarios/service/certificate-rotation-readiness/hostname-mismatch",
            "--collection-mode",
            "fixture",
            "--json",
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)

        self.assertEqual(payload["collection_mode"], "fixture")
        self.assertTrue(payload["generated"])

    def test_real_combination_rejects_linux_resource_conflict(self) -> None:
        result = self.run_cli(
            "run",
            "--combination",
            "scenarios/linux/disk-full/capacity,"
            "scenarios/linux/memory-oom/oom-kill",
            "--json",
        )
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        payload = json.loads(result.stdout)

        self.assertEqual(payload["collection_mode"], "real")
        self.assertTrue(payload["blocked"])
        self.assertEqual(payload["failure_class"], "resource_collision")
        self.assertTrue(
            any(
                "linux.mount/app-host/var-sre-agent conflicts with "
                "linux.evidenceFile/app-host/var-sre-agent-oom-events.log" in reason
                for reason in payload["blocking_reasons"]
            )
        )

    def test_random_compatible_combinations_exclude_shared_exclusive_resources(self) -> None:
        combinations = _random_compatible_combination_sets(
            ROOT,
            count=476,
            size=2,
            archetypes=["kind"],
            seed=20260505,
        )
        cert_paths = {
            (ROOT / "scenarios/service/certificate-rotation-readiness/expired").resolve(),
            (ROOT / "scenarios/service/certificate-rotation-readiness/expiring").resolve(),
            (ROOT / "scenarios/service/certificate-rotation-readiness/hostname-mismatch").resolve(),
        }
        coredns_mutators = cert_paths | {
            (ROOT / "scenarios/service/dns-tls-failure/expired").resolve(),
            (ROOT / "scenarios/service/dns-tls-failure/nxdomain").resolve(),
        }
        checkout_deployment_mutators = {
            (ROOT / "scenarios/kubernetes/crashloopbackoff/oom").resolve(),
            (ROOT / "scenarios/service/deployment-rollback-decision/dependency-no-rollback").resolve(),
            (ROOT / "scenarios/service/deployment-rollback-decision/insufficient-rollback-evidence").resolve(),
            (ROOT / "scenarios/service/deployment-rollback-decision/rollback-candidate").resolve(),
        }
        node_pressure_mutators = {
            (ROOT / "scenarios/kubernetes/node-pressure/disk-pressure").resolve(),
            (ROOT / "scenarios/kubernetes/node-pressure/memory-pressure").resolve(),
        }
        messaging_mutators = {
            (ROOT / "scenarios/service/queue-backlog-consumer-lag/consumer-capacity-drop").resolve(),
            (ROOT / "scenarios/service/queue-backlog-consumer-lag/consumer-lag-backlog").resolve(),
            (ROOT / "scenarios/service/queue-backlog-consumer-lag/dead-letter-backlog").resolve(),
        }

        self.assertEqual(len(combinations), 476)
        for combination in combinations:
            paths = {path.resolve() for path in combination}
            self.assertLessEqual(len(paths & cert_paths), 1)
            self.assertLessEqual(len(paths & coredns_mutators), 1)
            self.assertLessEqual(len(paths & checkout_deployment_mutators), 1)
            self.assertLessEqual(len(paths & node_pressure_mutators), 1)
            self.assertLessEqual(len(paths & messaging_mutators), 1)

    def test_random_compatible_combinations_exclude_linux_resource_conflicts(self) -> None:
        combinations = _random_compatible_combination_sets(
            ROOT,
            count=23,
            size=2,
            archetypes=["linux-vm"],
            seed=20260505,
        )
        disk_mutators = {
            (ROOT / "scenarios/linux/disk-full/capacity").resolve(),
            (ROOT / "scenarios/linux/disk-full/deleted-open-files").resolve(),
            (ROOT / "scenarios/linux/disk-full/inode-capacity").resolve(),
        }
        cpu_mutators = {
            (ROOT / "scenarios/linux/cpu-saturation/broad-saturation").resolve(),
            (ROOT / "scenarios/linux/cpu-saturation/hot-process").resolve(),
        }
        memory_mutators = {
            (ROOT / "scenarios/linux/memory-oom/hot-process").resolve(),
            (ROOT / "scenarios/linux/memory-oom/oom-kill").resolve(),
            (ROOT / "scenarios/linux/memory-oom/oom-prompt-injection").resolve(),
        }
        oom_event_writers = {
            (ROOT / "scenarios/linux/memory-oom/oom-kill").resolve(),
            (ROOT / "scenarios/linux/memory-oom/oom-prompt-injection").resolve(),
        }

        self.assertEqual(len(combinations), 23)
        for combination in combinations:
            paths = {path.resolve() for path in combination}
            self.assertLessEqual(len(paths & disk_mutators), 1)
            self.assertLessEqual(len(paths & cpu_mutators), 1)
            self.assertLessEqual(len(paths & memory_mutators), 1)
            self.assertFalse(paths & disk_mutators and paths & oom_event_writers)

    def test_cli_progress_keeps_json_stdout_parseable_and_writes_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = self.run_cli(
                "run",
                "--scenario",
                "scenarios/linux/disk-full/capacity",
                "--collection-mode",
                "fixture",
                "--json",
                "--progress",
                "--progress-artifact-dir",
                tmp,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            payload = json.loads(result.stdout)

            self.assertTrue(payload["generated"])
            self.assertIn("progress_artifacts", payload["context"])
            self.assertIn("run", result.stderr)
            events_path = Path(tmp) / "events.ndjson"
            summary_path = Path(tmp) / "summary.json"
            dashboard_path = Path(tmp) / "dashboard.json"
            dashboard_markdown_path = Path(tmp) / "dashboard.md"
            self.assertTrue(events_path.is_file())
            self.assertTrue(summary_path.is_file())
            self.assertTrue(dashboard_path.is_file())
            self.assertTrue(dashboard_markdown_path.is_file())
            events = [json.loads(line) for line in events_path.read_text().splitlines()]
            self.assertTrue(any(event["phase"] == "validate" and event["status"] == "ok" for event in events))
            self.assertEqual(json.loads(summary_path.read_text())["scenario"], "linux-disk-full-capacity")
            dashboard = json.loads(dashboard_path.read_text())
            self.assertEqual(dashboard["schema_version"], "incident-generator.progress-dashboard/v1")
            self.assertEqual(dashboard["failure_class"], "none")
            self.assertIn("dashboard", payload["context"]["progress_artifacts"])
            self.assertIn("dashboard_markdown", payload["context"]["progress_artifacts"])

    def test_real_run_progress_artifacts_include_lifecycle_events(self) -> None:
        package = load_scenario_package(ROOT / "scenarios/linux/disk-full/capacity")
        stream = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            reporter = OperatorProgressReporter(stream=stream, stream_format="human", artifact_dir=Path(tmp))

            result = stand_up_incident_environment(
                package,
                collection_mode="real",
                require_tools=True,
                dispatch_archetype_func=lambda *_args, **_kwargs: ArchetypeContext(
                    archetype="linux-vm",
                    host_env={},
                    runtime_state={
                        "archetype": "linux-vm",
                        "compose_project": "incident-generator-test",
                        "containers": [
                            {"name": "incident-generator-test-linux-target-1", "image": "sre-agent/linux-target:latest", "status": "Up"}
                        ],
                        "images": [{"repository": "sre-agent/linux-target:latest", "id": "sha256:test", "size": "12MB"}],
                    },
                ),
                seed_executor=_SuccessfulSeedExecutor(),
                symptom_waiter=_ProgressingWaiter(reporter),
                resolve_selectors_func=lambda *_args, **_kwargs: _SelectorResult(),
                start_port_forwards_func=lambda *_args, **_kwargs: _PortForwardRun(),
                progress_reporter=reporter,
            )
            reporter.close()

            self.assertFalse(result["blocked"])
            self.assertEqual(result["failure_class"], "none")
            self.assertIn("progress_artifacts", result["context"])
            events = [(event["phase"], event["status"]) for event in _read_ndjson(Path(tmp) / "events.ndjson")]
            self.assertIn(("archetype", "ok"), events)
            self.assertIn(("seed", "ok"), events)
            self.assertIn(("selector", "ok"), events)
            self.assertIn(("teardown", "ok"), events)
            self.assertIn("incident generation complete", stream.getvalue())
            dashboard = json.loads((Path(tmp) / "dashboard.json").read_text())
            self.assertEqual(dashboard["failure_class"], "none")
            self.assertEqual(dashboard["runtime_state"]["containers"][0]["name"], "incident-generator-test-linux-target-1")
            self.assertTrue(any(row["phase"] == "seed" and row["duration_ms"] >= 0 for row in dashboard["phase_timings"]))
            self.assertTrue(any(row["scenario"] == "linux-disk-full-capacity" for row in dashboard["seed_checkpoints"]))
            self.assertTrue(any(row["kind"] == "test_predicate" and row["matched"] is True for row in dashboard["wait_predicates"]))
            self.assertTrue(any(row["step"] == "seed_teardown" and row["status"] == "ok" for row in dashboard["teardown"]))
            self.assertIn("Runtime State", (Path(tmp) / "dashboard.md").read_text())

    def test_symptom_waiter_emits_predicate_observations(self) -> None:
        package = load_scenario_package(ROOT / "scenarios/linux/disk-full/capacity")
        expect = copy.deepcopy(package.expect)
        expect["wait_for"]["predicates"] = [{"kind": "test_predicate"}]
        package = ScenarioPackage(path=package.path, spec=package.spec, expect=expect)
        stream = io.StringIO()
        predicate = _EventuallyMatchedPredicate()
        waiter = SymptomWaiter(
            predicates={"test_predicate": predicate},
            sleep=lambda _seconds: None,
            progress_reporter=OperatorProgressReporter(stream=stream, stream_format="ndjson"),
        )

        result = waiter.wait(package, ArchetypeContext(archetype="linux-vm", host_env={}), {})

        self.assertFalse(result.failures)
        events = [json.loads(line) for line in stream.getvalue().splitlines()]
        observations = [event for event in events if event["phase"] == "wait_for" and event["status"] == "observed"]
        self.assertEqual([event["details"]["observed"]["calls"] for event in observations], [1, 2])
        self.assertTrue(observations[-1]["details"]["matched"])

    def test_chaos_mesh_phase_accepts_run_alias_for_running(self) -> None:
        def runner(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(args, 0, stdout="Run", stderr="")

        predicate = ChaosMeshPhasePredicate(command_runner=runner)
        result = predicate.evaluate(
            {"namespace": "network", "resource_kind": "networkchaos", "name": "latency-hop", "phase": "Running"},
            ArchetypeContext(archetype="kind", host_env={}),
            {},
        )

        self.assertTrue(result.matched)
        self.assertEqual(result.observed, "Run")

    def test_postgres_connection_count_accepts_exporter_metric_aliases(self) -> None:
        captured: list[list[str]] = []

        def runner(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            captured.append(args)
            return subprocess.CompletedProcess(args, 0, stdout='{"data":{"result":[{"value":[0,"31"]}]}}', stderr="")

        predicate = PostgresConnectionCountMinPredicate(command_runner=runner)
        result = predicate.evaluate(
            {"database": "checkout", "min": 30},
            ArchetypeContext(archetype="kind", host_env={"PROMETHEUS_URL": "http://localhost:9090"}),
            {},
        )

        self.assertTrue(result.matched)
        query_arg = next(arg for arg in captured[0] if arg.startswith("query="))
        self.assertIn('pg_stat_database_numbackends{datname="checkout"}', query_arg)
        self.assertIn('pg_stat_database_numbackends{database="checkout"}', query_arg)
        self.assertIn('pg_stat_activity_count{datname="checkout"}', query_arg)
        self.assertIn('pg_stat_activity_count{database="checkout"}', query_arg)

    def test_tls_certificate_failure_observes_debug_context(self) -> None:
        def runner(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
            if str(args[0]).endswith("check-tls.sh"):
                return subprocess.CompletedProcess(args, 2, stdout="partial tls stdout", stderr="openssl failed")
            if args[:5] == ["kubectl", "-n", "edge", "get", "service"]:
                return subprocess.CompletedProcess(args, 0, stdout="10.0.0.12", stderr="")
            if args[:5] == ["kubectl", "-n", "edge", "get", "endpoints"]:
                return subprocess.CompletedProcess(args, 1, stdout="", stderr="missing endpoints")
            if args[:5] == ["kubectl", "-n", "edge", "get", "pod"]:
                return subprocess.CompletedProcess(args, 0, stdout="Running", stderr="")
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="unexpected command")

        predicate = TlsCertificateInvalidPredicate(command_runner=runner)
        result = predicate.evaluate(
            {"namespace": "edge", "service": "edge-api", "hostname": "api.example.com"},
            ArchetypeContext(archetype="kind", host_env={}),
            {},
        )

        self.assertFalse(result.matched)
        self.assertEqual(result.observed["returncode"], 2)
        self.assertEqual(result.observed["stdout"], "partial tls stdout")
        self.assertEqual(result.observed["stderr"], "openssl failed")
        self.assertEqual(result.observed["kubernetes"]["service"], {"ok": True, "value": "10.0.0.12"})
        self.assertEqual(result.observed["kubernetes"]["endpoints"]["ok"], False)
        self.assertEqual(result.observed["kubernetes"]["probe"], {"ok": True, "value": "Running"})


class _SeedResult:
    failures: list[dict[str, str]] = []
    applied = True


class _FailingSeedResult:
    applied = False

    def __init__(self, check: str, error: str) -> None:
        self.failures = [{"check": check, "error": error}]


class _RecordingSeedExecutor:
    def __init__(self, events: list[tuple[str, str]]) -> None:
        self.events = events

    def apply(self, package: ScenarioPackage, *_args: object, **_kwargs: object) -> _SeedResult:
        self.events.append(("apply", package.name))
        return _SeedResult()

    def teardown(self, package: ScenarioPackage, *_args: object, **_kwargs: object) -> None:
        self.events.append(("teardown", package.name))


class _SuccessfulSeedExecutor:
    def apply(self, *_args: object, **_kwargs: object) -> _SeedResult:
        return _SeedResult()

    def teardown(self, *_args: object, **_kwargs: object) -> None:
        return None


class _FailingSeedExecutor:
    def __init__(self, check: str, error: str) -> None:
        self.check = check
        self.error = error

    def apply(self, *_args: object, **_kwargs: object) -> _FailingSeedResult:
        return _FailingSeedResult(self.check, self.error)

    def teardown(self, *_args: object, **_kwargs: object) -> None:
        return None


class _WaitResult:
    failures: list[dict[str, str]] = []


class _FailingWaitResult:
    def __init__(self, kind: str, error: str) -> None:
        self.failures = [{"kind": kind, "error": error}]


class _RecordingWaiter:
    def __init__(self, events: list[tuple[str, str]]) -> None:
        self.events = events

    def wait(self, package: ScenarioPackage, *_args: object, **_kwargs: object) -> _WaitResult:
        self.events.append(("wait", package.name))
        return _WaitResult()


class _SuccessfulWaiter:
    def wait(self, *_args: object, **_kwargs: object) -> _WaitResult:
        return _WaitResult()


class _FailingWaiter:
    def __init__(self, kind: str, error: str) -> None:
        self.kind = kind
        self.error = error

    def wait(self, *_args: object, **_kwargs: object) -> _FailingWaitResult:
        return _FailingWaitResult(self.kind, self.error)


class _ProgressingWaiter:
    def __init__(self, reporter: OperatorProgressReporter) -> None:
        self.reporter = reporter

    def wait(self, package: ScenarioPackage, *_args: object, **_kwargs: object) -> _WaitResult:
        self.reporter.emit(
            "wait_for",
            "started",
            "waiting for test predicate",
            details={"scenario": package.name, "predicate_count": 1, "timeout_seconds": 1, "interval_seconds": 0},
        )
        self.reporter.emit(
            "wait_for",
            "observed",
            "test_predicate matched",
            details={"scenario": package.name, "kind": "test_predicate", "matched": True, "observed": {"ready": True}},
        )
        self.reporter.emit(
            "wait_for",
            "ok",
            "all wait predicates matched",
            details={"scenario": package.name, "predicate_count": 1},
        )
        return _WaitResult()


class _SelectorResult:
    failures: list[dict[str, str]] = []
    metadata: dict[str, str] = {}


class _RecordingSelectorResult:
    failures: list[dict[str, str]] = []

    def __init__(self, package: ScenarioPackage, events: list[tuple[str, str]]) -> None:
        events.append(("select", package.name))
        self.metadata = {"scenario": package.name}


class _PortForwardRun:
    failures: list[dict[str, str]] = []
    forwards: list[object] = []

    def stop_all(self) -> None:
        return None


class _EventuallyMatchedPredicate:
    kind = "test_predicate"
    archetypes = ("linux-vm",)

    def __init__(self) -> None:
        self.calls = 0

    def evaluate(self, *_args: object, **_kwargs: object) -> PredicateResult:
        self.calls += 1
        return PredicateResult(matched=self.calls >= 2, observed={"calls": self.calls})


def _write_registry_artifacts(artifact_dir: Path) -> dict[str, object]:
    artifact_dir.mkdir(parents=True)
    payload: dict[str, object] = {
        "kind": "IncidentRunBatch",
        "batch": True,
        "count": 1,
        "generated": True,
        "blocked": False,
        "generated_count": 1,
        "blocked_count": 0,
        "collection_mode": "real",
        "combination_source": {
            "random": 1,
            "random_seed": 20260506,
            "random_combination_size": 2,
            "random_archetypes": ["kind"],
        },
        "failure_class": "none",
        "failure_classification": {"class": "none", "category": "none", "signals": [], "retriable": False},
        "runs": [
            {
                "generated": True,
                "blocked": False,
                "collection_mode": "real",
                "environment_archetype": "kind",
                "scenario": "combinatorial:service-http-5xx-spike-canary-rollout+database-connection-exhaustion-pool-saturation",
                "scenario_count": 2,
                "incident_session_id": "20260506-kind-random8-01",
                "failure_class": "none",
                "scenarios": [
                    {"name": "service-http-5xx-spike-canary-rollout"},
                    {"name": "database-connection-exhaustion-pool-saturation"},
                ],
                "context": {
                    "archetype": "kind",
                    "cluster": "sre-agent-phase-a",
                    "teardown": {"verified": True, "failures": []},
                },
            }
        ],
    }
    (artifact_dir / "result.json").write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    (artifact_dir / "summary.json").write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    (artifact_dir / "events.ndjson").write_text(
        json.dumps({"schema_version": "incident-generator.progress/v1", "phase": "batch", "status": "ok"}) + "\n",
        encoding="utf-8",
    )
    (artifact_dir / "dashboard.json").write_text(
        json.dumps({"schema_version": "incident-generator.progress-dashboard/v1", "status": "generated"}) + "\n",
        encoding="utf-8",
    )
    return payload


def _valid_workload_profile() -> dict[str, object]:
    return {
        "id": "linux-vm/app-host-lite",
        "main_service": "checkout-api",
        "warmup_seconds": 30,
        "load_generator": {
            "seed": 20260506,
            "rps": 12.5,
            "concurrency": 4,
            "traffic_mix": {"checkout": 0.7, "cart": 0.3},
            "dependency_fanout": {"postgres": 1, "redis": 1},
            "retry_behavior": {"strategy": "exponential_backoff", "max_attempts": 2},
        },
        "noise_profile": {
            "id": "warm-batch-background",
            "ambient_signal_sources": ["node.cpu", "service.http", "postgres.connections"],
        },
    }


def _valid_incident_injection(expected_hypothesis: str) -> dict[str, object]:
    return {
        "kind": "disk_fill",
        "starts_after_warmup": True,
        "causal_signal_sources": ["linux.disk_usage", "linux.directory_sizes"],
        "expected_hypothesis": expected_hypothesis,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_ndjson(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


if __name__ == "__main__":
    unittest.main()
