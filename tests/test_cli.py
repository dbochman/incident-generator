from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path


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

