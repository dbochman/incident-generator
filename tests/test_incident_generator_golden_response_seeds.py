from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any

import yaml


def _project_root() -> Path:
    package_root = Path(__file__).resolve().parents[1]
    if (package_root / "harness").is_dir():
        return package_root
    return package_root.parents[1]


ROOT = _project_root()
SEEDS_PATH = ROOT / "harness/golden-response-seeds.yaml"
ALIASES_PATH = ROOT / "harness/alpha-benchmark-sets.yaml"

HIDDEN_LEARNER_LABELS = {
    "causal",
    "contextual",
    "ambient",
    "red_herring",
    "hostile",
}
FORBIDDEN_PROMPT_INJECTION_OUTPUT = {
    "SVCPWN",
    "shift_all_traffic",
}


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


class GoldenResponseSeedTests(unittest.TestCase):
    def test_seed_library_references_release_inputs_and_checked_evidence(self) -> None:
        manifest = _load_yaml(SEEDS_PATH)
        aliases = _load_yaml(ALIASES_PATH)
        alias_rows = {row["alias"]: row for row in aliases["aliases"]}
        known_sets = {set_id for row in alias_rows.values() for set_id in row["benchmark_set_ids"]}

        self.assertEqual(manifest["schema_version"], "incident-generator.golden-response-seeds/v1")
        self.assertEqual(manifest["release"], aliases["release"])
        self.assertEqual(len(manifest["seeds"]), 11)

        for seed in manifest["seeds"]:
            with self.subTest(seed=seed["id"]):
                self.assertIn(seed["release_alias"], alias_rows)
                self.assertIn(seed["benchmark_set_id"], known_sets)
                self.assertTrue(seed["scenario_ids"])
                self.assertTrue(seed["release_manifest_paths"])
                self.assertTrue(seed["redaction_checks"])
                self.assertTrue(seed["validation_commands"])

                for relative in seed["source_manifests"]:
                    self.assertTrue((ROOT / relative).exists(), relative)

                evidence_ids = {item["id"] for item in seed["learner_visible_evidence"]}
                self.assertTrue(evidence_ids)
                for item in seed["learner_visible_evidence"]:
                    ref_path = item["ref"].split("#", 1)[0]
                    self.assertTrue((ROOT / ref_path).is_file(), item["ref"])
                    self.assertTrue(item["observation"])

                response = seed["supervised_response"]
                for evidence_id in evidence_ids:
                    self.assertIn(f"`{evidence_id}`", response)
                for hypothesis in seed["expected_hypotheses"]:
                    self.assertIn(hypothesis["id"], response)
                    self.assertIn(hypothesis["confidence"], {"low", "medium", "high"})

    def test_seed_responses_hide_scoring_labels_and_forbidden_prompt_outputs(self) -> None:
        manifest = _load_yaml(SEEDS_PATH)

        for seed in manifest["seeds"]:
            with self.subTest(seed=seed["id"]):
                learner_visible_text = "\n".join(
                    [seed["supervised_response"]]
                    + [item["observation"] for item in seed["learner_visible_evidence"]]
                )
                tokens = set(learner_visible_text.replace("-", "_").split())
                self.assertTrue(HIDDEN_LEARNER_LABELS.isdisjoint(tokens))
                for forbidden in FORBIDDEN_PROMPT_INJECTION_OUTPUT:
                    self.assertNotIn(forbidden, learner_visible_text)
                self.assertNotIn("/home/", learner_visible_text)
                self.assertNotIn("SECRET_", learner_visible_text)
                self.assertNotIn("API_KEY", learner_visible_text)


if __name__ == "__main__":
    unittest.main()
