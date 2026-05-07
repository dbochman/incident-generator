# Skill Drill Export

`python3 -m incident_generator skill-drill-export` materializes portable training bundles from the checked seed libraries.

Each bundle is written under `<output-dir>/<benchmark_set_id>/<golden_seed_id>/` with:

- `drill.md` — learner-facing prompt and reviewed evidence observations only.
- `expected-evidence.yaml` — reviewer-facing expected evidence refs, expected hypotheses, redaction checks, and validation commands.
- `supervised-response.md` — the reviewed positive response.
- `incorrect-responses.yaml` — linked training negatives, when available.
- `provenance.json` — release, source manifests, source hashes, release-manifest paths, evidence hashes, and linked negative ids.

The export also writes top-level `manifest.json` and `curriculum.json`. The curriculum file preserves the checked beginner, intermediate, and advanced drill ordering from `harness/training-curriculum-order.yaml`.

Run:

```bash
python3 -m incident_generator skill-drill-export \
  --output-dir dist/training-drills \
  --created-at 2026-05-06T00:00:00Z \
  --json
```

The export manifest uses schema `incident-generator.skill-drill-export/v1`. `release-manifest` also records the command, source hashes, bundle file list, curriculum hash, 11 reviewed bundles, and six linked incorrect-response examples.
