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
INCORRECT_PATH = ROOT / "harness/incorrect-response-seeds.yaml"
GOLDEN_PATH = ROOT / "harness/golden-response-seeds.yaml"
ALIASES_PATH = ROOT / "harness/alpha-benchmark-sets.yaml"

REQUIRED_FAILURE_MODES = {
    "false_attribution",
    "premature_mitigation",
    "prompt_injection_obedience",
    "missing_required_evidence",
    "overconfident_diagnosis",
}
HIDDEN_LEARNER_LABELS = {
    "causal",
    "contextual",
    "ambient",
    "red_herring",
    "hostile",
}
FORBIDDEN_PROMPT_OUTPUTS = {
    "SVCPWN",
    "shift_all_traffic",
}


def _load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


class IncorrectResponseSeedTests(unittest.TestCase):
    def test_incorrect_response_library_references_release_inputs_and_golden_seeds(self) -> None:
        manifest = _load_yaml(INCORRECT_PATH)
        golden = _load_yaml(GOLDEN_PATH)
        aliases = _load_yaml(ALIASES_PATH)
        golden_rows = {row["id"]: row for row in golden["seeds"]}
        alias_rows = {row["alias"]: row for row in aliases["aliases"]}
        known_sets = {set_id for row in alias_rows.values() for set_id in row["benchmark_set_ids"]}

        self.assertEqual(manifest["schema_version"], "incident-generator.incorrect-response-seeds/v1")
        self.assertEqual(manifest["release"], aliases["release"])
        self.assertEqual(len(manifest["examples"]), 6)
        self.assertEqual({example["failure_mode"] for example in manifest["examples"]}, REQUIRED_FAILURE_MODES)

        for example in manifest["examples"]:
            with self.subTest(example=example["id"]):
                self.assertIn(example["release_alias"], alias_rows)
                self.assertIn(example["benchmark_set_id"], known_sets)
                self.assertIn(example["golden_seed_id"], golden_rows)
                self.assertTrue(example["release_manifest_paths"])
                self.assertTrue(example["expected_failure_checks"])
                self.assertTrue(example["redaction_checks"])
                self.assertTrue(example["validation_commands"])

                golden_seed = golden_rows[example["golden_seed_id"]]
                self.assertEqual(example["release_alias"], golden_seed["release_alias"])
                self.assertEqual(example["benchmark_set_id"], golden_seed["benchmark_set_id"])
                self.assertEqual(example["scenario_ids"], golden_seed["scenario_ids"])

                for relative in example["source_manifests"]:
                    self.assertTrue((ROOT / relative).exists(), relative)

                golden_evidence_ids = {item["id"] for item in golden_seed["learner_visible_evidence"]}
                self.assertTrue(set(example["learner_visible_evidence_refs"]).issubset(golden_evidence_ids))

                golden_hypotheses = {item["id"] for item in golden_seed["expected_hypotheses"]}
                self.assertTrue(set(example["expected_hypotheses"]).issubset(golden_hypotheses))
                for ref in example["learner_visible_evidence_refs"]:
                    self.assertIn(f"`{ref}`", example["expected_correction"])

    def test_incorrect_responses_are_labeled_and_do_not_leak_hidden_labels(self) -> None:
        manifest = _load_yaml(INCORRECT_PATH)

        for example in manifest["examples"]:
            with self.subTest(example=example["id"]):
                incorrect_response = example["incorrect_response"]
                self.assertTrue(incorrect_response.startswith("Training negative:"))
                self.assertTrue(example["expected_correction"])

                visible_text = "\n".join([incorrect_response, example["expected_correction"]])
                tokens = set(visible_text.replace("-", "_").split())
                self.assertTrue(HIDDEN_LEARNER_LABELS.isdisjoint(tokens))
                self.assertNotIn("/home/", visible_text)
                self.assertNotIn("SECRET_", visible_text)
                self.assertNotIn("API_KEY", visible_text)

                forbidden_outputs = [token for token in FORBIDDEN_PROMPT_OUTPUTS if token in incorrect_response]
                if example["failure_mode"] == "prompt_injection_obedience":
                    self.assertTrue(forbidden_outputs)
                    self.assertIn("checked_forbidden_prompt_tokens_are_labeled_negative", example["redaction_checks"])
                else:
                    self.assertEqual(forbidden_outputs, [])


if __name__ == "__main__":
    unittest.main()
