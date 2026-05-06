# Benchmark Result Schema

`schemas/incident-generator-benchmark-result.schema.json` defines the comparison payload for benchmark entrants. Use it after generating incidents and running one or more agents against the same cases.

The schema version is `incident-generator.benchmark-result/v1`. A checked example is available at `harness/benchmark-result-schema-example.json`.

## What It Records

| Section | Purpose |
| --- | --- |
| `benchmark_set` | Benchmark set id, seed, collection modes, case count, and source references. |
| `cases` | Generated incident metadata: scenario ids, combination size, archetype, collection mode, generation state, failure class, expectations, and artifact references. |
| `entrants` | Compared agents: deterministic replay, fixture-backed LLM, live LLM, external adapter, or hybrid, including model and judge metadata when present. |
| `results` | Per-case entrant outcomes: diagnosis, matched/missing hypotheses, evidence refs, evidence discipline, abstention, uncertainty, false-attribution guards, judge outcome, duration, and failure class. |
| `aggregate` | Counts for pass/fail/block/skip, agent regressions, false attribution, abstention, uncertainty, and judge execution. |

## Suggested Flow

1. Preview a benchmark set with `pair-preview`, `triple-preview`, `adversarial-combos`, `evidence-discipline-combos`, `conflicting-signal-combos`, `temporal-model`, or `recovery-benchmark`.
2. Run fixture or real incidents with `run`, retaining `result.json`, `events.ndjson`, and `summary.json` when live evidence matters.
3. Register retained run artifacts with `artifact-registry add` when hashes and host metadata are needed.
4. Run deterministic replay, a live LLM agent, or an external entrant adapter.
5. Emit one `incident-generator.benchmark-result/v1` document that points to the retained artifacts and records the per-entrant outcomes.

The schema is intentionally a comparison contract, not an artifact store. Keep raw prompts, raw model outputs, credentials, and unredacted evidence dumps in separate retained artifacts with explicit references.

External entrants should use `schemas/incident-generator-agent-adapter.schema.json` and `harness/agent-adapter-contract-example.json` for the redacted evidence request and structured response handoff. The `benchmark-runner` command can replay that checked exchange or invoke a local `--adapter-command`, then emit one schema-valid comparison payload. See `docs/agent-adapter-contract.md`.
