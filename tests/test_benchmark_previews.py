from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from incident_generator.benchmark_previews import (
    render_random_pair_fixture_preview,
    render_triple_benchmark_fixture_preview,
)


ROOT = Path(__file__).resolve().parents[1]


class TripleBenchmarkFixturePreviewTests(unittest.TestCase):
    def test_preview_preserves_selected_triples_and_expected_hypotheses(self) -> None:
        report = render_triple_benchmark_fixture_preview(ROOT)
        repeated = render_triple_benchmark_fixture_preview(ROOT)

        self.assertEqual(report["schema_version"], "sre-agent.triple-benchmark-fixture-preview/v1")
        self.assertEqual(report["preview_id"], "triple-benchmark-fixture-preview")
        self.assertTrue(report["passed"], report["failures"])
        self.assertTrue(report["deterministic"])
        self.assertEqual(report["seed"], 20260506)
        self.assertEqual(report["collection_mode"], "fixture")
        self.assertEqual(report["combination_size"], 3)
        self.assertEqual(report["scenario_pool_count"], 9)
        self.assertEqual(report["candidate_pool"]["count"], 84)
        self.assertEqual(report["candidate_pool"]["included_count"], 84)
        self.assertEqual(report["selected_count"], 8)
        self.assertEqual(report["artifact_hash"], repeated["artifact_hash"])
        self.assertEqual(
            report["coverage"]["selected_domains"],
            ["database", "kubernetes", "linux", "network", "service"],
        )
        self.assertEqual(report["coverage"]["selected_archetypes"], ["kind", "linux-vm"])
        self.assertIn("oom_killed_process", report["coverage"]["expected_hypotheses"])
        for row in report["selected"]:
            with self.subTest(combination=row["combination_id"]):
                self.assertTrue(row["compatible"], row["compatibility_reasons"])
                self.assertEqual(len(row["scenario_ids"]), 3)
                self.assertEqual(len(row["scenario_paths"]), 3)
                self.assertEqual(len(row["expected_hypotheses"]), 3)
                self.assertEqual(
                    sorted(
                        hypothesis
                        for expected in row["expected_hypotheses"]
                        for hypothesis in expected["expected_hypotheses"]
                    ),
                    row["expected_hypothesis_set"],
                )
                self.assertTrue(all(not path.startswith("/") for path in row["scenario_paths"]))

    def test_cli_renders_triple_preview_report(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "incident_generator",
                "triple-preview",
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
        self.assertEqual(payload["selected_count"], 8)
        self.assertEqual(payload["candidate_pool"]["compatibility_mode"], "fixture")
        self.assertEqual(payload["selected"][0]["combination_id"], "triple-benchmark-fixture-preview-triple-01")


class RandomPairFixturePreviewTests(unittest.TestCase):
    def test_preview_preserves_seeded_real_compatible_kind_pairs(self) -> None:
        report = render_random_pair_fixture_preview(ROOT)
        repeated = render_random_pair_fixture_preview(ROOT)

        self.assertEqual(report["schema_version"], "sre-agent.random-pair-fixture-preview/v1")
        self.assertEqual(report["preview_id"], "kind-random-pair-preview-20260506")
        self.assertTrue(report["passed"], report["failures"])
        self.assertTrue(report["deterministic"])
        self.assertEqual(report["seed"], 20260506)
        self.assertEqual(report["preview_mode"], "fixture")
        self.assertEqual(report["compatibility_mode"], "real")
        self.assertEqual(report["archetype"], "kind")
        self.assertEqual(report["combination_size"], 2)
        self.assertEqual(report["scenario_pool_count"], 32)
        self.assertEqual(report["candidate_pool"]["count"], 496)
        self.assertEqual(report["candidate_pool"]["included_count"], 476)
        self.assertEqual(report["candidate_pool"]["rejected_count"], 20)
        self.assertEqual(report["selected_count"], 8)
        self.assertEqual(report["artifact_hash"], repeated["artifact_hash"])
        self.assertEqual(report["coverage"]["selected_archetypes"], ["kind"])
        self.assertEqual(report["coverage"]["selected_domains"], ["database", "kubernetes", "network", "service"])
        self.assertIn("service-http-5xx-spike-canary-rollout", report["coverage"]["selected_scenario_ids"])
        self.assertIn("kubernetes-pending-pod-taint-mismatch", report["coverage"]["selected_scenario_ids"])
        self.assertEqual(
            report["selected"][0]["scenario_ids"],
            [
                "database-connection-exhaustion-connection-storm",
                "service-certificate-rotation-readiness-expired",
            ],
        )
        self.assertEqual(report["selected"][0]["resource_claim_summary"]["claim_count"], 6)
        for row in report["selected"]:
            with self.subTest(combination=row["combination_id"]):
                self.assertTrue(row["compatible"], row["compatibility_reasons"])
                self.assertEqual(len(row["scenario_ids"]), 2)
                self.assertEqual(row["target_state_conflict_count"], 0)
                self.assertTrue(all(not path.startswith("/") for path in row["scenario_paths"]))

    def test_cli_renders_pair_preview_report(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "incident_generator",
                "pair-preview",
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
        self.assertEqual(payload["selected_count"], 8)
        self.assertEqual(payload["candidate_pool"]["compatibility_mode"], "real")
        self.assertEqual(payload["selected"][0]["combination_id"], "kind-random-pair-preview-20260506-pair-01")


if __name__ == "__main__":
    unittest.main()
