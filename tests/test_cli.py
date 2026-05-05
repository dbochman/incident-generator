from __future__ import annotations

import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from incident_generator.checks import check_fixture_hygiene, check_markdown_links
from incident_generator.scenarios import ScenarioPackage, load_scenario_package, validate_scenario_package


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


if __name__ == "__main__":
    unittest.main()
