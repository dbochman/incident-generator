from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from incident_generator.noisy_fixtures import render_noisy_fixture_bundle
from incident_generator.scenarios import load_scenario_package


ROOT = Path(__file__).resolve().parents[1]


class NoisyFixtureRendererTests(unittest.TestCase):
    def test_renderer_combines_fixture_outputs_with_catalog_noise(self) -> None:
        package = load_scenario_package(ROOT / "scenarios/service/dns-tls-failure/nxdomain")

        bundle = render_noisy_fixture_bundle(ROOT, package, seed=20260506, max_noise_sources=3)
        repeated = render_noisy_fixture_bundle(ROOT, package, seed=20260506, max_noise_sources=3)

        self.assertEqual(bundle["schema_version"], "sre-agent.noisy-fixture-bundle/v1")
        self.assertEqual(bundle["scenario"], "service-dns-tls-failure-nxdomain")
        self.assertEqual(bundle["expected_hypotheses"], ["dns_resolution_failure"])
        self.assertEqual(bundle["artifact_hash"], repeated["artifact_hash"])
        self.assertEqual(len(bundle["artifact_hash"]), 64)
        self.assertEqual(bundle["noise_profile"]["id"], "edge-noise")
        self.assertEqual(len(bundle["noise_profile"]["source_ids"]), 3)
        self.assertGreaterEqual(bundle["signal_role_counts"]["causal"], 2)
        self.assertGreaterEqual(bundle["signal_role_counts"]["ambient"], 3)
        self.assertFalse(bundle["role_taxonomy"]["agent_visible_role_labels"])
        self.assertFalse(bundle["untrusted_data_framing"]["agent_visible_role_labels"])

    def test_agent_visible_chunks_do_not_expose_internal_roles_or_sources(self) -> None:
        package = load_scenario_package(ROOT / "scenarios/service/dns-tls-failure/nxdomain")
        bundle = render_noisy_fixture_bundle(ROOT, package, seed=7, max_noise_sources=2)
        role_values = {"causal", "contextual", "ambient", "red_herring", "hostile"}

        for entry in bundle["evidence"]:
            with self.subTest(evidence_ref=entry["evidence_ref"]):
                visible = json.dumps(entry["agent_visible"], sort_keys=True)
                self.assertNotIn("signal_role", visible)
                self.assertNotIn("source_id", visible)
                self.assertNotIn(entry["internal"]["source_id"], visible)
                self.assertFalse(any(f'"{role}"' in visible for role in role_values))
                self.assertTrue(entry["agent_visible"]["untrusted_data"])

    def test_prompt_injection_fixture_adds_hostile_internal_marker(self) -> None:
        package = load_scenario_package(ROOT / "scenarios/service/http-5xx-spike/prompt-injection")

        bundle = render_noisy_fixture_bundle(ROOT, package, seed=20260506)

        self.assertGreaterEqual(bundle["signal_role_counts"]["hostile"], 1)
        self.assertTrue(
            any(
                entry["internal"]["signal_role"] == "hostile"
                and entry["internal"]["source_id"] == "adversarial_fixture.hostile_text"
                for entry in bundle["evidence"]
            )
        )

    def test_cli_renders_noisy_fixture_manifest_json(self) -> None:
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "incident_generator",
                "noisy-fixture",
                "--scenario",
                "scenarios/service/dns-tls-failure/nxdomain",
                "--seed",
                "7",
                "--max-noise-sources",
                "2",
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
        self.assertEqual(payload["schema_version"], "sre-agent.noisy-fixture-bundle/v1")
        self.assertEqual(payload["seed"], 7)
        self.assertEqual(len(payload["noise_profile"]["source_ids"]), 2)
        self.assertEqual(len(payload["artifact_hash"]), 64)


if __name__ == "__main__":
    unittest.main()
