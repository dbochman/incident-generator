from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml

from incident_generator.skill_drill_export import export_skill_drill_bundles


def _project_root() -> Path:
    package_root = Path(__file__).resolve().parents[1]
    if (package_root / "harness").is_dir():
        return package_root
    return package_root.parents[1]


ROOT = _project_root()


class IncidentGeneratorSkillDrillExportTests(unittest.TestCase):
    def test_export_writes_portable_training_bundle_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "training-drills"
            manifest = export_skill_drill_bundles(
                ROOT,
                output_dir=output_dir,
                created_at="2026-05-06T00:00:00Z",
            )

            self.assertEqual(manifest["schema_version"], "incident-generator.skill-drill-export/v1")
            self.assertEqual(manifest["release"], "alpha-2026-05-06")
            self.assertEqual(manifest["bundle_count"], 11)
            self.assertEqual(manifest["incorrect_response_count"], 6)
            self.assertEqual(manifest["curriculum"]["schema_version"], "incident-generator.training-curriculum/v1")
            self.assertEqual(manifest["curriculum"]["entry_count"], 11)
            self.assertTrue((output_dir / "curriculum.json").is_file())

            bundles = {row["bundle_id"]: row for row in manifest["bundles"]}
            disk_bundle = bundles["golden-linux-disk-capacity"]
            bundle_dir = output_dir / disk_bundle["bundle_path"]
            for filename in manifest["bundle_files"]:
                with self.subTest(filename=filename):
                    self.assertTrue((bundle_dir / filename).is_file())
                    self.assertEqual(
                        disk_bundle["files"][filename]["sha256"],
                        _sha256_file(bundle_dir / filename),
                    )

            drill = (bundle_dir / "drill.md").read_text(encoding="utf-8")
            self.assertIn("Linux disk capacity diagnosis", drill)
            self.assertIn("`fs-summary`", drill)
            self.assertIn("/var is 95% used", drill)
            self.assertNotIn("`disk_capacity`", drill)
            self.assertNotIn(str(ROOT), drill)

            expected = yaml.safe_load((bundle_dir / "expected-evidence.yaml").read_text(encoding="utf-8"))
            self.assertEqual(expected["schema_version"], "incident-generator.skill-drill-expected-evidence/v1")
            self.assertEqual(expected["expected_hypotheses"][0]["id"], "disk_capacity")

            incorrect = yaml.safe_load((bundle_dir / "incorrect-responses.yaml").read_text(encoding="utf-8"))
            self.assertEqual(incorrect["schema_version"], "incident-generator.skill-drill-incorrect-responses/v1")
            self.assertEqual(incorrect["example_count"], 1)
            self.assertEqual(incorrect["examples"][0]["failure_mode"], "premature_mitigation")

            provenance = json.loads((bundle_dir / "provenance.json").read_text(encoding="utf-8"))
            self.assertEqual(provenance["schema_version"], "incident-generator.skill-drill-provenance/v1")
            self.assertEqual(provenance["golden_seed_id"], "golden-linux-disk-capacity")
            self.assertEqual(provenance["incorrect_response_ids"], ["incorrect-linux-disk-premature-cleanup"])
            self.assertTrue(all(row["kind"] != "missing" for row in provenance["source_hashes"]))

            curriculum = json.loads((output_dir / "curriculum.json").read_text(encoding="utf-8"))
            self.assertEqual(curriculum["entries"][0]["golden_seed_id"], "golden-linux-disk-capacity")
            self.assertEqual(curriculum["entries"][0]["bundle_path"], disk_bundle["bundle_path"])

    def test_cli_exports_skill_drill_bundle_manifest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            output_dir = Path(tmp) / "training-drills"
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "incident_generator",
                    "skill-drill-export",
                    "--output-dir",
                    str(output_dir),
                    "--created-at",
                    "2026-05-06T00:00:00Z",
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
        self.assertEqual(payload["schema_version"], "incident-generator.skill-drill-export/v1")
        self.assertEqual(payload["bundle_count"], 11)
        self.assertEqual(payload["incorrect_response_count"], 6)
        self.assertEqual(payload["created_at"], "2026-05-06T00:00:00Z")


def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    unittest.main()
