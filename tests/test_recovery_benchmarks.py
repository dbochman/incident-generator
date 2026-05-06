from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from incident_generator.recovery_benchmarks import render_recovery_after_diagnosis_benchmark


ROOT = Path(__file__).resolve().parents[1]


class RecoveryAfterDiagnosisBenchmarkTests(unittest.TestCase):
    def test_recovery_benchmark_preserves_gates_evidence_and_dry_run_boundary(self) -> None:
        report = render_recovery_after_diagnosis_benchmark(ROOT)
        repeated = render_recovery_after_diagnosis_benchmark(ROOT)

        self.assertEqual(report["schema_version"], "sre-agent.recovery-after-diagnosis-benchmark-report/v1")
        self.assertEqual(report["benchmark_schema_version"], "sre-agent.recovery-after-diagnosis-benchmark/v1")
        self.assertEqual(report["benchmark_id"], "recovery-after-diagnosis-alpha")
        self.assertTrue(report["passed"], report["failures"])
        self.assertEqual(report["case_count"], 2)
        self.assertEqual(report["safe_dry_run_case_count"], 2)
        self.assertEqual(report["hold_case_count"], 0)
        self.assertEqual(report["artifact_hash"], repeated["artifact_hash"])
        self.assertEqual(report["coverage"]["action_classes"], [3])
        self.assertEqual(report["coverage"]["action_categories"], ["code_change", "shell"])
        self.assertIn("kubectl-rollout-undo", report["coverage"]["action_template_ids"])
        self.assertIn("bump-helm-resource-limit", report["coverage"]["action_template_ids"])
        for row in report["cases"]:
            self.assertTrue(row["initial_requires_action_abstention"])
            self.assertFalse(row["expected_transition"]["mutations_invoked"])
            self.assertTrue(row["expected_transition"]["dry_run_required"])
            self.assertEqual(
                set(row["expected_transition"]["required_gates"]),
                {"domain_supervisor", "generalist_supervisor", "human_confirmation"},
            )
            self.assertTrue(row["evidence_preservation"]["all_preserved_refs_in_diagnosis"])
            self.assertTrue(row["evidence_preservation"]["all_preserved_refs_in_scenario"])

    def test_cli_renders_recovery_benchmark_report(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "incident_generator",
                "recovery-benchmark",
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
        self.assertEqual(payload["case_count"], 2)
        self.assertEqual(payload["collection_mode"], "fixture")


if __name__ == "__main__":
    unittest.main()
