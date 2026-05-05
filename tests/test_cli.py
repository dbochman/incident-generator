from __future__ import annotations

import copy
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

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
    load_scenario_package,
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
        self.assertTrue(any("eks-staging" in reason for reason in result["blocking_reasons"]))

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
        self.assertTrue(any("same environment_archetype" in reason for reason in payload["blocking_reasons"]))

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

    def test_real_combination_reuses_one_archetype_and_tears_down_each_seed(self) -> None:
        packages = [
            load_scenario_package(ROOT / "scenarios/linux/disk-full/capacity"),
            load_scenario_package(ROOT / "scenarios/linux/memory-oom/oom-kill"),
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
        self.assertEqual(result["environment_archetype"], "linux-vm")
        self.assertEqual(result["context"]["seed_results"], [
            {"scenario": "linux-disk-full-capacity", "applied": True},
            {"scenario": "linux-memory-oom-oom-kill", "applied": True},
        ])
        self.assertIn(("dispatch", "linux-vm"), events)
        self.assertLess(
            events.index(("teardown", "linux-memory-oom-oom-kill")),
            events.index(("teardown", "linux-disk-full-capacity")),
        )
        self.assertEqual(events[-1], ("archetype-teardown", "linux-vm"))

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

    def test_random_compatible_combinations_exclude_shared_exclusive_resources(self) -> None:
        combinations = _random_compatible_combination_sets(
            ROOT,
            count=493,
            size=2,
            archetypes=["kind"],
            seed=20260505,
        )
        cert_paths = {
            (ROOT / "scenarios/service/certificate-rotation-readiness/expired").resolve(),
            (ROOT / "scenarios/service/certificate-rotation-readiness/expiring").resolve(),
            (ROOT / "scenarios/service/certificate-rotation-readiness/hostname-mismatch").resolve(),
        }

        self.assertEqual(len(combinations), 493)
        for combination in combinations:
            self.assertLessEqual(sum(1 for path in combination if path.resolve() in cert_paths), 1)

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
            self.assertTrue(events_path.is_file())
            self.assertTrue(summary_path.is_file())
            events = [json.loads(line) for line in events_path.read_text().splitlines()]
            self.assertTrue(any(event["phase"] == "validate" and event["status"] == "ok" for event in events))
            self.assertEqual(json.loads(summary_path.read_text())["scenario"], "linux-disk-full-capacity")

    def test_real_run_progress_artifacts_include_lifecycle_events(self) -> None:
        package = load_scenario_package(ROOT / "scenarios/linux/disk-full/capacity")
        stream = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            reporter = OperatorProgressReporter(stream=stream, stream_format="human", artifact_dir=Path(tmp))

            result = stand_up_incident_environment(
                package,
                collection_mode="real",
                require_tools=True,
                dispatch_archetype_func=lambda *_args, **_kwargs: ArchetypeContext(archetype="linux-vm", host_env={}),
                seed_executor=_SuccessfulSeedExecutor(),
                symptom_waiter=_SuccessfulWaiter(),
                resolve_selectors_func=lambda *_args, **_kwargs: _SelectorResult(),
                start_port_forwards_func=lambda *_args, **_kwargs: _PortForwardRun(),
                progress_reporter=reporter,
            )
            reporter.close()

            self.assertFalse(result["blocked"])
            self.assertIn("progress_artifacts", result["context"])
            events = [(event["phase"], event["status"]) for event in _read_ndjson(Path(tmp) / "events.ndjson")]
            self.assertIn(("archetype", "ok"), events)
            self.assertIn(("seed", "ok"), events)
            self.assertIn(("selector", "ok"), events)
            self.assertIn(("teardown", "ok"), events)
            self.assertIn("incident generation complete", stream.getvalue())

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


class _WaitResult:
    failures: list[dict[str, str]] = []


class _RecordingWaiter:
    def __init__(self, events: list[tuple[str, str]]) -> None:
        self.events = events

    def wait(self, package: ScenarioPackage, *_args: object, **_kwargs: object) -> _WaitResult:
        self.events.append(("wait", package.name))
        return _WaitResult()


class _SuccessfulWaiter:
    def wait(self, *_args: object, **_kwargs: object) -> _WaitResult:
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


def _read_ndjson(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


if __name__ == "__main__":
    unittest.main()
