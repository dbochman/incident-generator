from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from incident_generator.noisy_smoke import render_noisy_smoke_report


ROOT = Path(__file__).resolve().parents[1]


class NoisySmokeReportTests(unittest.TestCase):
    def test_checkout_vertical_smoke_report_preserves_expected_hypotheses(self) -> None:
        report = render_noisy_smoke_report(ROOT)
        repeated = render_noisy_smoke_report(ROOT)

        self.assertEqual(report["schema_version"], "sre-agent.noisy-smoke-report/v1")
        self.assertEqual(report["smoke_id"], "noisy-checkout-vertical-smoke")
        self.assertTrue(report["passed"], report["failures"])
        self.assertEqual(report["scenario_count"], 5)
        self.assertEqual(report["passed_count"], 5)
        self.assertEqual(report["artifact_hash"], repeated["artifact_hash"])
        self.assertEqual(report["coverage"]["main_services"], ["checkout-api"])
        self.assertTrue({"api-noise", "data-noise", "platform-noise", "client-noise"}.issubset(report["coverage"]["noise_profiles"]))
        self.assertIn("database.connection_churn", report["coverage"]["source_ids"])
        self.assertIn("kubernetes.normal_event", report["coverage"]["source_ids"])
        self.assertIn("edge.dns_retry", report["coverage"]["source_ids"])
        for row in report["scenarios"]:
            with self.subTest(scenario=row["scenario"]):
                self.assertTrue(row["passed"], row["failures"])
                self.assertTrue(row["observed_expected_hypothesis"])
                self.assertTrue(row["fixture_replay_generated"])
                self.assertGreater(row["noisy_fixture"]["signal_role_counts"]["causal"], 0)
                self.assertGreater(row["noisy_fixture"]["signal_role_counts"]["ambient"], 0)

    def test_cli_renders_noisy_smoke_report(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "incident_generator",
                "noisy-smoke",
                "--json",
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["passed"], payload["failures"])
        self.assertEqual(payload["scenario_count"], 5)
        self.assertIsNone(payload["max_noise_sources"])


if __name__ == "__main__":
    unittest.main()
