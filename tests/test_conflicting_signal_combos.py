from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from incident_generator.conflicting_signal_combos import render_conflicting_signal_combo_report


ROOT = Path(__file__).resolve().parents[1]


class ConflictingSignalComboPackageTests(unittest.TestCase):
    def test_renderer_reports_conflicting_signal_combo_coverage(self) -> None:
        report = render_conflicting_signal_combo_report(ROOT)
        repeated = render_conflicting_signal_combo_report(ROOT)

        self.assertEqual(report["schema_version"], "sre-agent.conflicting-signal-combos/v1")
        self.assertTrue(report["passed"], report["failures"])
        self.assertEqual(report["combo_count"], 3)
        self.assertEqual(report["artifact_hash"], repeated["artifact_hash"])
        self.assertEqual(
            set(report["coverage"]["signal_axes"]),
            {"deploy_vs_dependency", "latency_vs_database", "rollback_vs_dependency"},
        )
        self.assertEqual(report["coverage"]["confidence_ceiling_counts"], {"medium": 3})

    def test_cli_renders_conflicting_signal_combo_report(self) -> None:
        completed = subprocess.run(
            [sys.executable, "-m", "incident_generator", "conflicting-signal-combos", "--json"],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
        payload = json.loads(completed.stdout)
        self.assertTrue(payload["passed"], payload["failures"])
        self.assertEqual(payload["combo_count"], 3)


if __name__ == "__main__":
    unittest.main()
