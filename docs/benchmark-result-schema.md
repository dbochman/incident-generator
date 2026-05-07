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
4. Run deterministic replay, a live LLM agent, noisy live artifact replay, or an external entrant adapter.
5. Emit one `incident-generator.benchmark-result/v1` document that points to the retained artifacts and records the per-entrant outcomes.

The schema is intentionally a comparison contract, not an artifact store. Keep raw prompts, raw model outputs, credentials, and unredacted evidence dumps in separate retained artifacts with explicit references.

`deterministic-replay-result` converts validated-combo replay summaries such as `harness/deterministic-replay-summary-example.json` into this schema for deterministic entrant comparison. `llm-smoke-result` converts recorded fixture/live LLM smoke summaries such as `harness/benchmark-combo-llm-smoke-fixture-summary.json` and `harness/benchmark-combo-llm-smoke-live-summary.json` into the same schema without rerunning providers or storing credential values. `noisy-live-result` converts retained noisy live artifact-registry entries into the same schema by verifying retained hashes, live run state, noisy smoke expected-hypothesis coverage, loadgen metadata, cleanup state, abstention expectations, and internal evidence-role counts without rerunning live infrastructure; `harness/noisy-database-live-smoke.yaml` records the retained database run id, benchmark set id, artifact layout, and replay command for this same payload shape. External entrants should use `schemas/incident-generator-agent-adapter.schema.json`, `harness/agent-adapter-contract-example.json`, and `harness/agent-adapter-benchmark-set.yaml` for redacted evidence requests and structured response handoffs. The `benchmark-runner` command can replay one checked exchange, invoke a local `--adapter-command`, or run `--benchmark-set` to merge selected cases into one schema-valid comparison payload with optional retained artifacts. `result-comparison` renders a Markdown table across result payloads for pass rate, hypothesis preservation, abstention, uncertainty, false-attribution guards, judge state, latency, and artifact links. `--judge-pack deterministic-local` records executed deterministic judge outcomes; Tier 2 and mixed packs are selected metadata that currently fail closed. See `docs/benchmark-result-comparison.md`, `docs/noisy-database-live-smoke.md`, `docs/agent-adapter-contract.md`, and `docs/judge-pack-selection.md`.
