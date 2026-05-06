from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from incident_generator.temporal_benchmarks import render_temporal_benchmark_model


ROOT = Path(__file__).resolve().parents[1]


class TemporalBenchmarkModelTests(unittest.TestCase):
    def test_temporal_model_report_preserves_phase_order_and_hypothesis_updates(self) -> None:
        report = render_temporal_benchmark_model(ROOT)
        repeated = render_temporal_benchmark_model(ROOT)

        self.assertEqual(report["schema_version"], "sre-agent.temporal-benchmark-model-report/v1")
        self.assertEqual(report["model_schema_version"], "sre-agent.temporal-incident-benchmark/v1")
        self.assertEqual(report["model_id"], "checkout-deploy-db-cascade")
        self.assertTrue(report["passed"], report["failures"])
        self.assertEqual(report["phase_count"], 5)
        self.assertEqual(report["causal_link_count"], 3)
        self.assertEqual(report["delayed_symptom_count"], 3)
        self.assertEqual(report["artifact_hash"], repeated["artifact_hash"])
        self.assertEqual(
            [phase["id"] for phase in report["phases"]],
            ["baseline", "canary-regression", "database-backpressure", "latency-symptom", "stabilization"],
        )
        self.assertEqual(report["phases"][1]["expected_hypotheses"]["active"], ["deploy_correlated_5xx"])
        self.assertEqual(
            report["phases"][3]["expected_hypotheses"]["active"],
            ["deploy_correlated_5xx", "deploy_correlated_latency", "pool_exhausted"],
        )
        self.assertEqual(
            report["phases"][4]["expected_hypotheses"]["active"],
            ["deploy_correlated_latency", "pool_exhausted"],
        )
        self.assertIn("canary-regression->database-backpressure", report["coverage"]["causal_edges"])
        self.assertIn("delayed_symptom", report["coverage"]["phase_kinds"])

    def test_cli_renders_temporal_model_report(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "incident_generator",
                "temporal-model",
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
        self.assertEqual(payload["phase_count"], 5)
        self.assertEqual(payload["collection_mode"], "fixture")


if __name__ == "__main__":
    unittest.main()
