# Golden Response Seeds

`harness/golden-response-seeds.yaml` defines reviewed supervised responses for the `alpha-2026-05-06` benchmark release. The library turns selected benchmark incidents into training seeds without exposing hidden scoring labels or live provider credentials.

Each seed links to:

- a stable benchmark alias and benchmark set id from `harness/alpha-benchmark-sets.yaml`;
- release manifest paths for the scenario, set, and alias rows;
- learner-visible evidence refs under checked fixture or harness sources;
- expected hypotheses and confidence;
- redaction checks and validation commands;
- a concise supervised response with evidence citations.

`python3 -m incident_generator release-manifest --json` publishes the library under `benchmark_release.training_seed_library`. The release manifest includes source hashes, evidence refs, expected hypotheses, validation commands, and a sha256 of the response text; the full response text remains in `harness/golden-response-seeds.yaml` for review.

Coverage includes Linux disk byte and inode capacity, Linux OOM kill, checkout 5xx deploy correlation, DNS NXDOMAIN, database pool exhaustion, Kubernetes insufficient CPU and PVC-unbound scheduling, network high-latency path, HTTP dependency failure with prompt-injection evidence, and a low-signal unknown/abstention disk case.

Validate changes with:

```sh
python3 -m unittest tests.test_incident_generator_golden_response_seeds
python3 -m incident_generator release-manifest --json
python3 -m incident_generator docs-check
```
