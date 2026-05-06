from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from incident_generator.noisy_partial_failures import render_noisy_partial_failure_pack


ROOT = Path(__file__).resolve().parents[1]


class NoisyPartialFailurePackTests(unittest.TestCase):
    def test_pack_report_covers_partial_failure_modes_and_roles(self) -> None:
        report = render_noisy_partial_failure_pack(ROOT)
        repeated = render_noisy_partial_failure_pack(ROOT)

        self.assertEqual(report["schema_version"], "sre-agent.noisy-partial-failure-pack-report/v1")
        self.assertEqual(report["pack_id"], "noisy-partial-failure-pack")
        self.assertTrue(report["passed"], report["failures"])
        self.assertEqual(report["variant_count"], 4)
        self.assertEqual(report["passed_count"], 4)
        self.assertEqual(report["artifact_hash"], repeated["artifact_hash"])
        self.assertEqual(
            set(report["coverage"]["failure_modes"]),
            {
                "partial_seed_success",
                "missing_wait_for_evidence",
                "degraded_but_not_down",
                "unrelated_noisy_evidence",
            },
        )
        self.assertIn("ambient", report["coverage"]["internal_roles"])
        self.assertIn("red_herring", report["coverage"]["internal_roles"])
        self.assertEqual(report["coverage"]["main_services"], ["checkout-api"])
        self.assertIn("api-noise", report["coverage"]["noise_profiles"])
        self.assertIn("data-noise", report["coverage"]["noise_profiles"])

        by_mode = {row["failure_mode"]: row for row in report["variants"]}
        self.assertEqual(by_mode["partial_seed_success"]["seed_result"]["status"], "partial")
        self.assertEqual(by_mode["missing_wait_for_evidence"]["wait_for_evidence"]["status"], "missing")
        self.assertEqual(by_mode["degraded_but_not_down"]["expected_hypothesis"], "insufficient_rollback_evidence")
        self.assertGreater(
            by_mode["unrelated_noisy_evidence"]["noisy_fixture"]["combined_signal_role_counts"]["red_herring"],
            0,
        )

    def test_cli_renders_partial_failure_pack_report(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "incident_generator",
                "noisy-partial-failures",
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
        self.assertEqual(payload["variant_count"], 4)
        self.assertIsNone(payload["max_noise_sources"])


if __name__ == "__main__":
    unittest.main()
