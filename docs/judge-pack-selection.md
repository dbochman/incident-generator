# Judge Pack Selection

`harness/agent-adapter-judge-packs.yaml` defines the external adapter benchmark judge modes exported with the package.

```bash
python3 -m incident_generator judge-packs --json
```

The checked packs are:

| Pack | Judge kind | Status |
| --- | --- | --- |
| `deterministic-local` | `deterministic` | Executable through local benchmark-runner scoring. |
| `llm-tier2-separate-family` | `llm_tier2` | Selected metadata only; benchmark-runner blocks until live judge execution exists. |
| `mixed-deterministic-tier2` | `mixed` | Selected metadata only; deterministic scoring must run before a future separate-family Tier 2 judge. |

Run the selected adapter set with deterministic judge outcomes:

```bash
python3 -m incident_generator benchmark-runner \
  --benchmark-set harness/agent-adapter-benchmark-set.yaml \
  --judge-pack deterministic-local \
  --artifact-dir .tmp/benchmark-runner-artifacts \
  --json
```

Tier 2 and mixed packs require a judge model family different from the entrant model family. Until live judge execution is implemented, those selections produce schema-valid blocked results instead of fabricated judge verdicts.
