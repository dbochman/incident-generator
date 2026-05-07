# Incorrect Response Seeds

`harness/incorrect-response-seeds.yaml` defines reviewed training negatives for the `alpha-2026-05-06` benchmark release. These examples are intentionally incorrect and remain separate from learner-visible benchmark evidence and positive supervised responses.

Each example links to:

- a reviewed golden response seed from `harness/golden-response-seeds.yaml`;
- a stable benchmark alias and benchmark set id from `harness/alpha-benchmark-sets.yaml`;
- release manifest paths for the scenario, set, alias, and golden seed rows;
- learner-visible evidence refs that the incorrect response mishandles;
- the expected failure mode and deterministic failure checks;
- a correction note that points back to the safe evidence-cited response shape;
- redaction checks and validation commands.

`python3 -m incident_generator release-manifest --json` publishes the library under `benchmark_release.incorrect_response_library`. The release manifest includes source hashes, failure modes, evidence refs, expected hypotheses, validation commands, and sha256 hashes of the incorrect response and correction text; the full review text remains in `harness/incorrect-response-seeds.yaml`.

Coverage includes premature mitigation, prompt-injection obedience, missing required evidence, overconfident diagnosis, and DNS/TLS false attribution.

Validate changes with:

```sh
python3 -m unittest tests.test_incident_generator_incorrect_response_seeds
python3 -m incident_generator release-manifest --json
python3 -m incident_generator docs-check
```
