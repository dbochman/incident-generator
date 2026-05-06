# Noisy Fixture Renderer

`incident_generator noisy-fixture` renders a deterministic internal manifest for noisy benchmark fixture previews. It combines checked fixture output hashes with selected production-noise source IDs and internal signal roles without changing clean fixture-mode runs.

Example:

```sh
python3 -m incident_generator noisy-fixture \
  --scenario scenarios/service/dns-tls-failure/nxdomain \
  --seed 20260506 \
  --max-noise-sources 3 \
  --json
```

The manifest uses `harness/production-noise-source-catalog.yaml` and `harness/evidence-signal-role-taxonomy.yaml`, preserves expected hypotheses, marks agent-visible chunks as untrusted data, strips role/source metadata from agent-visible entries, and records a stable `artifact_hash`. The noisy smoke and partial-failure pack reports consume these manifests for deterministic replay.
