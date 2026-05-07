from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from incident_generator.noisy_live_results import render_noisy_live_result


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
ROOT = PACKAGE_ROOT if (PACKAGE_ROOT / "benchmark-artifacts/registry.json").is_file() else PACKAGE_ROOT.parents[1]


class NoisyLiveResultTests(unittest.TestCase):
    def test_retained_noisy_live_run_maps_to_benchmark_result(self) -> None:
        payload = render_noisy_live_result(ROOT, created_at="2026-05-06T00:00:00Z")

        self.assertEqual(payload["schema_version"], "incident-generator.benchmark-result/v1")
        self.assertEqual(payload["benchmark_set"]["benchmark_set_id"], "noisy-checkout-live-20260506")
        self.assertEqual(payload["aggregate"]["case_count"], 1)
        self.assertEqual(payload["aggregate"]["passed_count"], 1)
        self.assertEqual(payload["aggregate"]["required_abstentions"], 1)
        self.assertEqual(payload["results"][0]["state"], "passed")
        self.assertEqual(payload["results"][0]["diagnosis"]["primary_hypothesis"], "deploy_correlated_5xx")
        self.assertEqual(payload["entrants"][0]["agent_kind"], "deterministic")
        self.assertEqual(payload["entrants"][0]["execution_mode"], "replay")
        self.assertTrue(
            any(
                ref["kind"] == "harness_plan" and ref["ref"] == "harness/noisy-checkout-vertical-smoke.yaml"
                for ref in payload["benchmark_set"]["source_refs"]
            )
        )
        self.assertIn("service incident", payload["cases"][0]["notes"])

    def test_database_noisy_live_run_maps_to_benchmark_result(self) -> None:
        payload = render_noisy_live_result(
            ROOT,
            run_id="20260506-noisy-live-database-pool-exhausted",
            benchmark_set_id="noisy-database-live-20260506",
            created_at="2026-05-06T00:00:00Z",
        )

        self.assertEqual(payload["schema_version"], "incident-generator.benchmark-result/v1")
        self.assertEqual(payload["benchmark_set"]["benchmark_set_id"], "noisy-database-live-20260506")
        self.assertEqual(payload["aggregate"]["case_count"], 1)
        self.assertEqual(payload["aggregate"]["passed_count"], 1)
        self.assertEqual(payload["aggregate"]["required_abstentions"], 1)
        self.assertEqual(payload["results"][0]["state"], "passed")
        self.assertEqual(payload["results"][0]["diagnosis"]["primary_hypothesis"], "pool_exhausted")
        self.assertTrue(payload["results"][0]["scoring"]["overall_pass"])
        self.assertTrue(
            any(
                ref["kind"] == "harness_plan" and ref["ref"] == "harness/noisy-database-live-smoke.yaml"
                for ref in payload["benchmark_set"]["source_refs"]
            )
        )
        self.assertIn("database incident", payload["cases"][0]["notes"])

    def test_cli_emits_noisy_live_result_payload(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "incident_generator",
                "--root",
                str(ROOT),
                "noisy-live-result",
                "--created-at",
                "2026-05-06T00:00:00Z",
                "--json",
            ],
            cwd=PACKAGE_ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertEqual(payload["result_id"], "noisy-checkout-live-20260506.noisy-live-replay")
        self.assertEqual(payload["aggregate"]["judge_executed_count"], 1)


if __name__ == "__main__":
    unittest.main()
