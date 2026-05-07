from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

from incident_generator.training_curriculum import TrainingCurriculumError, build_training_curriculum


def _project_root() -> Path:
    package_root = Path(__file__).resolve().parents[1]
    if (package_root / "harness").is_dir():
        return package_root
    return package_root.parents[1]


ROOT = _project_root()


class IncidentGeneratorTrainingCurriculumTests(unittest.TestCase):
    def test_curriculum_orders_every_reviewed_seed_once(self) -> None:
        payload = build_training_curriculum(ROOT)
        golden = yaml.safe_load((ROOT / "harness/golden-response-seeds.yaml").read_text(encoding="utf-8"))
        incorrect = yaml.safe_load((ROOT / "harness/incorrect-response-seeds.yaml").read_text(encoding="utf-8"))

        self.assertEqual(payload["schema_version"], "incident-generator.training-curriculum/v1")
        self.assertEqual(payload["release"], "alpha-2026-05-06")
        self.assertEqual(payload["difficulty_order"], ["beginner", "intermediate", "advanced"])
        self.assertEqual(payload["level_count"], 3)
        self.assertEqual(payload["entry_count"], 11)
        self.assertEqual(payload["golden_seed_count"], len(golden["seeds"]))
        self.assertEqual(payload["incorrect_response_count"], len(incorrect["examples"]))
        self.assertEqual(payload["domain_count"], 5)
        self.assertTrue(all(row["kind"] != "missing" for row in payload["source_refs"]))

        entries = payload["entries"]
        self.assertEqual([entry["order"] for entry in entries], list(range(1, 12)))
        self.assertEqual({entry["golden_seed_id"] for entry in entries}, {seed["id"] for seed in golden["seeds"]})
        rows = {entry["golden_seed_id"]: entry for entry in entries}
        self.assertEqual(rows["golden-linux-disk-capacity"]["paired_negative_ids"], ["incorrect-linux-disk-premature-cleanup"])
        self.assertEqual(rows["golden-service-dns-nxdomain"]["paired_negative_ids"], ["incorrect-service-dns-nxdomain-cert-renewal"])
        self.assertEqual(rows["golden-linux-memory-oom-kill"]["paired_negative_ids"], ["incorrect-linux-memory-oom-premature-restart"])
        self.assertEqual(rows["golden-kubernetes-pending-pvc-unbound"]["prerequisite_seed_ids"], ["golden-kubernetes-pending-insufficient-cpu"])
        self.assertEqual(rows["golden-service-http-5xx-prompt-injection"]["difficulty"], "advanced")
        self.assertEqual(
            rows["golden-service-http-5xx-prompt-injection"]["prerequisite_seed_ids"],
            ["golden-service-http-5xx-deploy-correlated"],
        )

    def test_cli_emits_curriculum_summary(self) -> None:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "incident_generator",
                "training-curriculum",
                "--json",
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["schema_version"], "incident-generator.training-curriculum/v1")
        self.assertEqual(payload["entry_count"], 11)
        self.assertEqual(payload["entries"][0]["golden_seed_id"], "golden-linux-disk-capacity")

    def test_curriculum_rejects_non_contiguous_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            curriculum = yaml.safe_load((ROOT / "harness/training-curriculum-order.yaml").read_text(encoding="utf-8"))
            curriculum["levels"][0]["domains"][0]["items"][0]["order"] = 99
            curriculum_path = Path(tmp) / "curriculum.yaml"
            curriculum_path.write_text(yaml.safe_dump(curriculum, sort_keys=False), encoding="utf-8")

            with self.assertRaisesRegex(TrainingCurriculumError, "contiguous"):
                build_training_curriculum(ROOT, curriculum_path=curriculum_path)


if __name__ == "__main__":
    unittest.main()
