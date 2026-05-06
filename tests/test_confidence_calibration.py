from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from incident_generator.confidence_calibration import render_confidence_calibration_report


ROOT = Path(__file__).resolve().parents[1]


class ConfidenceCalibrationPackageTests(unittest.TestCase):
    def test_renderer_reports_confidence_calibration_coverage(self) -> None:
        report = render_confidence_calibration_report(ROOT)
        repeated = render_confidence_calibration_report(ROOT)

        self.assertEqual(report["schema_version"], "sre-agent.confidence-calibration-report/v1")
        self.assertTrue(report["passed"], report["failures"])
        self.assertEqual(report["case_count"], 11)
        self.assertEqual(report["artifact_hash"], repeated["artifact_hash"])
        self.assertEqual(report["coverage"]["evidence_quality_counts"], {"high": 5, "low": 1, "medium": 5})
        self.assertEqual(report["coverage"]["agent_counts"], {"deterministic": 11, "live_llm_snapshot": 11})
        self.assertEqual(report["coverage"]["over_target_count"], 1)

    def test_cli_renders_confidence_calibration_report(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "incident_generator", "confidence-calibration", "--json"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["passed"], payload["failures"])
        self.assertEqual(payload["case_count"], 11)
        self.assertEqual(payload["coverage"]["bounded_pass_count"], 22)


if __name__ == "__main__":
    unittest.main()
