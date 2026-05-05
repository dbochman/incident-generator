from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from incident_generator.checks import check_fixture_hygiene, check_markdown_links
from incident_generator.scenarios import (
    ArchetypeContext,
    ScenarioPackage,
    dispatch_archetype,
    load_scenario_package,
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

class _SeedResult:
    failures: list[dict[str, str]] = []
    applied = True


class _SuccessfulSeedExecutor:
    def apply(self, *_args: object, **_kwargs: object) -> _SeedResult:
        return _SeedResult()

    def teardown(self, *_args: object, **_kwargs: object) -> None:
        return None


class _WaitResult:
    failures: list[dict[str, str]] = []


class _SuccessfulWaiter:
    def wait(self, *_args: object, **_kwargs: object) -> _WaitResult:
        return _WaitResult()


class _SelectorResult:
    failures: list[dict[str, str]] = []
    metadata: dict[str, str] = {}


class _PortForwardRun:
    failures: list[dict[str, str]] = []
    forwards: list[object] = []

    def stop_all(self) -> None:
        return None


if __name__ == "__main__":
    unittest.main()
