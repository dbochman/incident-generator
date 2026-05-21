# CrisisMode Support Progress

This page tracks the incident-generator side of CrisisMode compatibility: what is checked in, what confidence it gives us, and what should happen next. The current work is intentionally scoped to incident-generator. It does not modify CrisisMode itself.

## Current State

Incident-generator now has a fixture-safe CrisisMode compatibility path:

- `incident_generator crisismode-adapter` reads `incident-generator.agent-adapter-request/v1` on stdin and emits `incident-generator.agent-adapter-response/v1`.
- `incident_generator crisismode-adapter --stdio-jsonl` supports the v2 investigation-session protocol for fixture-backed tool discovery and final responses.
- `incident_generator crisismode-compatibility` runs the checked CrisisMode benchmark set and emits a compatibility report.
- `incident_generator crisismode-compatibility --adapter-command ...` can score a real CrisisMode adapter command with the same response-schema, plan-shape, benchmark, and coverage report used for the local shim.
- `harness/crisismode-compatibility-benchmark-set.yaml` covers 21 cases across the CrisisMode-style support surface.
- The strict report can discover a sibling CrisisMode checkout with `--crisismode-repo ../crisismode` and fail closed when expected agent-family coverage is missing.

The CrisisMode checkout has also started aligning to this contract. As of
`ab46c4d feat(bundle): integrate SRE-skills evidence-bundle v1`, CrisisMode
has TypeScript mirrors of `incident-generator.agent-adapter/v1`, bundle
ingest/respond/execute entry points, action-template and action-policy mapping,
and tests for evidence ingestion, response generation, routing, action policy,
and bundle-to-plan translation. This is structural alignment, not yet a passing
end-to-end benchmark against CrisisMode's real runtime.

The compatibility report currently checks:

- benchmark scoring with `deterministic-local`
- real adapter command scoring when `--adapter-command` is supplied
- real CrisisMode route metadata from `agent.model.router.recommendedAgent`, `agent.model.router.scenarios[*].agentKind`, or `agent.adapter_id`
- response schema shape against the local adapter response contract
- CrisisMode-style plan shape for dry-run, human-approved recovery actions
- expected abstention and uncertainty behavior
- agent-family coverage discovered from the CrisisMode checkout

The latest incident-generator shim gate is:

- 21/21 checked CrisisMode compatibility cases passed
- 19/19 discovered CrisisMode agent families covered
- schema validation passed
- plan-shape validation passed
- v1 adapter smoke passed
- v2 stdio-jsonl adapter smoke passed

With the current sibling CrisisMode checkout at `ab46c4d`, strict discovery
finds 19 built-in CrisisMode agent families and the local shim reports
`agent_family_coverage: 19/19`. The seven families that were previously
uncovered now have fixture-safe compatibility cases: `dns`, `tls`, `disk`,
`backup`, `aws-s3`, `aws-dynamodb`, and `aws-rds`.

## Covered Incident Families

The checked compatibility set exercises:

- PostgreSQL connection exhaustion
- PostgreSQL replication lag
- Redis memory pressure
- queue backlog
- Kafka consumer lag
- etcd consensus instability
- Ceph storage degradation
- Flink checkpoint failure
- deploy rollback
- config drift
- Kubernetes crash loop
- AI provider failover
- database migration recovery
- DNS resolution failure
- TLS certificate failure
- disk capacity exhaustion
- backup verification failure
- AWS S3 degradation
- AWS DynamoDB throttling
- AWS RDS failover instability
- ambiguous evidence abstention

This gives us a broad compatibility signal, but it is still a fixture-backed signal.

## What This Does Not Prove

The local shim proves the adapter contract, scoring surface, response shape, and coverage accounting. It does not prove that CrisisMode's real agents already make the same decisions.

Specifically, the current support does not yet:

- pass the checked benchmark through CrisisMode's production adapter command
- execute CrisisMode's real routing layer
- run CrisisMode agents against live evidence
- validate real CrisisMode tool execution
- guarantee route accuracy inside CrisisMode
- replace CrisisMode's own unit, integration, or end-to-end tests

The current CrisisMode `bundle respond -` command can be invoked by
`incident_generator crisismode-compatibility --adapter-command ...`, so the
process/protocol boundary is close. In the local check on 2026-05-21, the
21-case compatibility report ran CrisisMode's command successfully and response
schema validation passed. Incident-generator now reads CrisisMode's real route
metadata from `agent.model.router.recommendedAgent`, normalizes CrisisMode's
internal family names (`message-queue`, `application`, `application-config`,
and `managed-database`) to the compatibility family names, and reports route
coverage separately from benchmark scoring. The current real command still does
not pass deterministic scoring in the no-key local probe: all 21 cases failed,
all 21 responses abstained, and agent-family coverage was `12/19`. The missing
families are the seven newer CrisisMode families: `dns`, `tls`, `disk`,
`backup`, `aws-s3`, `aws-dynamodb`, and `aws-rds`. Plan-shape validation passes
because no malformed recovery plans are emitted; the benchmark and mutation-gate
checks still fail because expected diagnosis cases do not emit non-abstaining
hypotheses or recovery-plan actions.

For local NVIDIA Inference Gateway experiments, keep credentials out of this
repository and configure the sibling CrisisMode checkout at runtime:

```sh
export NVIDIA_API_KEY="<redacted>"
export CRISISMODE_AI_PROVIDER=openai-compatible
export CRISISMODE_AI_BASE_URL=https://inference-api.nvidia.com
export CRISISMODE_AI_MODEL=<model-id-from-/v1/models>
```

Do not set `ANTHROPIC_API_KEY` to the NVIDIA key; the NVIDIA gateway uses an
OpenAI-compatible `/v1/chat/completions` API shape. Incident-generator only
invokes the adapter command and records the result. It does not store provider
credentials.

The `us/aws/anthropic/bedrock-claude-opus-4-6` model id is only usable when the
NVIDIA token is entitled to that route. In the 2026-05-21 local live probe, the
gateway accepted the test token for `/v1/models` but denied that Bedrock Claude
route with `key_model_access_denied`. Using an allowed model returned by
`/v1/models`, `nvcf/meta/llama-3.3-70b-instruct`, produced a real completion and
let the sibling CrisisMode `bundle respond -` command return a non-abstaining
response for the adapter contract fixture: `state: succeeded`, three
hypotheses, and two proposed inspection actions.

The same 2026-05-21 live setup was then run through a three-case compatibility
sample and the full 21-case compatibility probe. The three-case sample passed
Redis memory pressure, produced the expected PostgreSQL pool hypothesis but
missed the required uncertainty statement, and correctly abstained on the
ambiguous fixture while failing evidence-reference scoring. The full live probe
returned valid adapter-response schema for every case, but the overall gate
failed:

- 5/21 benchmark cases passed: Redis memory, Kafka consumer lag, etcd
  consensus, Ceph storage, and config drift.
- 16/21 cases failed deterministic scoring, mostly because live hypotheses used
  semantically close wording that did not match the checked expected strings.
- Plan-shape validation failed for 20/21 cases. The common issues were missing
  `crisismode_plan` details on draft recovery actions and missing
  `unsafe_actions_avoided`; PostgreSQL replication and Kubernetes crash-loop
  drafts also dropped required evidence refs.
- Route coverage remained `12/19`; the real CrisisMode router still mapped
  `dns`, `tls`, `disk`, `backup`, `aws-s3`, `aws-dynamodb`, and `aws-rds`
  fixtures onto older families instead of the newer discovered agent families.
- The ambiguous case preserved abstention and uncertainty semantics, emitted no
  proposed actions, and failed only the evidence-reference check.

The report now exposes those findings directly instead of requiring manual JSON
mining:

- `case_summary` gives a compact per-case view with state, failed checks,
  primary hypothesis, matched or missing expected hypotheses, proposed actions,
  route match, schema status, and plan-shape errors.
- `route_validation` compares expected and observed CrisisMode agent family per
  case and reports route mismatches separately from diagnosis correctness. The
  ambiguous abstention case is marked not applicable because it should not force
  one CrisisMode recovery family.
- `plan_shape_validation.cases[*].error_details` adds structured paths,
  expected values, observed values, and remediation hints for missing
  `crisismode_plan`, missing evidence refs, missing human-approval gates, and
  missing `unsafe_actions_avoided`.

Deterministic scoring should remain the CI baseline. An LLM judge may be useful
as a secondary live-run adjudicator for semantically equivalent hypotheses, but
it should not replace deterministic scoring for contract gates until its prompt,
rubric, cost, retry behavior, and failure modes are explicitly checked. The
current deterministic failures are therefore useful signal: some are genuine
route or plan-shape gaps, and some are candidates for either narrow canonical
aliases or an optional LLM-assisted review lane.

Treat the current work as a compatibility harness and regression target. The next milestone is wiring CrisisMode itself into this harness.

## Validation Commands

When running from this repository without installing the embedded package, set:

```sh
export PYTHONPATH=packages/incident-generator
```

Run the strict report when a sibling CrisisMode checkout is available:

```sh
python3 -m incident_generator crisismode-compatibility \
  --crisismode-repo ../crisismode \
  --strict \
  --json
```

Run the strict report against the current sibling checkout and expect the shim
benchmarks, schema checks, plan-shape checks, and discovered family coverage to
pass:

```sh
python3 -m incident_generator crisismode-compatibility \
  --crisismode-repo /home/dbochman/repos/crisismode \
  --strict \
  --json
```

Run the expanded compatibility benchmark directly against the local shim:

```sh
python3 -m incident_generator benchmark-runner \
  --benchmark-set harness/crisismode-compatibility-benchmark-set.yaml \
  --adapter-command "python3 -m incident_generator crisismode-adapter" \
  --judge-pack deterministic-local \
  --json
```

Run the basic v1 smoke set:

```sh
python3 -m incident_generator benchmark-runner \
  --benchmark-set harness/agent-adapter-benchmark-set.yaml \
  --adapter-command "python3 -m incident_generator crisismode-adapter" \
  --judge-pack deterministic-local \
  --json
```

Run the v2 investigation-session smoke set:

```sh
python3 -m incident_generator benchmark-runner \
  --benchmark-set harness/agent-adapter-benchmark-set.yaml \
  --input-mode investigation-session \
  --adapter-protocol stdio-jsonl \
  --adapter-command "python3 -m incident_generator crisismode-adapter --stdio-jsonl" \
  --judge-pack deterministic-local \
  --json
```

Validate a live OpenAI-compatible provider before running the 21-case live
probe:

```sh
python3 -m incident_generator crisismode-provider-smoke \
  --json
```

The command reads `CRISISMODE_AI_API_KEY`, `NVIDIA_API_KEY`, or
`NVIDIA_INFERENCE_API_KEY` from the environment, reads the selected model from
`CRISISMODE_AI_MODEL` or `NVIDIA_MODEL`, calls `/v1/models`, and then makes one
`/v1/chat/completions` request. It is intended to catch missing keys, denied
model routes, and base-URL mistakes before a full live compatibility run.

Score CrisisMode's real bundle responder from the compatibility report:

```sh
python3 -m incident_generator crisismode-compatibility \
  --adapter-command "corepack pnpm@10.30.3 --dir /home/dbochman/repos/crisismode exec tsx src/cli/index.ts bundle respond -" \
  --json
```

This probe validates the local process handoff and adapter stdin/stdout shape.
Without a configured local model endpoint, the real CrisisMode command is
expected to abstain. With the local NVIDIA environment variables above, the same
probe exercises CrisisMode's live response generation through the gateway.

## Recommended Next Work

1. Make the real CrisisMode adapter command pass scoring.

   CrisisMode now has `bundle respond -`, and incident-generator can score it
   directly through `crisismode-compatibility --adapter-command`. Incident-generator
   now recognizes CrisisMode's real route metadata, so the remaining runtime work
   is to make that command return benchmark-aligned, non-abstaining diagnoses for
   diagnosis cases; preserve exact abstention semantics for ambiguous evidence;
   cite visible evidence ids; emit recovery-plan actions for the allowed
   `draft_*` action ids; and route the seven newer families.

2. Add a CrisisMode CI gate.

   Run `crisismode-compatibility --strict --adapter-command ...` in CI with the
   real adapter command. The gate should fail on benchmark regressions, schema
   violations, unsafe plan shape, missing abstention, adapter runtime errors,
   route mismatches, or missing agent-family coverage.

3. Use route validation to fix real-command routing.

   `route_validation` now reports expected and observed CrisisMode agent family
   separately from diagnosis correctness. Use that table to debug the live
   router paths that still map `dns`, `tls`, `disk`, `backup`, `aws-s3`,
   `aws-dynamodb`, and `aws-rds` fixtures onto older families.

4. Keep discovered-family coverage current.

   The current sibling checkout's 19 discovered families are covered. Future
   CrisisMode agent families should add a fixture-safe exchange, benchmark-set
   row, routing profile, and plan-shape expectation before
   `crisismode-compatibility --strict --crisismode-repo ...` is treated as
   green against the expanded surface.

5. Expand negative and ambiguity cases.

   Add weak-signal and red-herring cases where CrisisMode should avoid
   over-routing: weak database noise, deploy timing coincidences, Kubernetes
   event noise without crash-loop evidence, storage symptoms with insufficient
   causal evidence, cloud-provider noise without service impact, and multi-agent
   ambiguity that should preserve uncertainty.

6. Harden v2 investigation behavior.

   Add stdio-jsonl cases for malformed tool results, unavailable tools, adapter timeout, partial evidence discovery, duplicate tool calls, and final responses that cite undiscovered evidence ids.

7. Deepen safety coverage.

   Add more dry-run and human-approval checks around rollback, DB migration, AI provider failover, storage repair, and consensus recovery. These are the cases where a correct diagnosis can still lead to unsafe action proposals.

8. Improve report ergonomics.

   `case_summary` now gives a compact JSON view. The remaining ergonomic step is
   Markdown or JUnit output for `crisismode-compatibility` so CI failures are
   readable without opening the full JSON payload.

## Ownership Boundary

Incident-generator should own:

- adapter request/response contracts
- checked evidence fixtures
- benchmark scoring and deterministic judge packs
- compatibility report shape
- schema and plan-shape gates
- regression documentation

CrisisMode should own:

- the real adapter command
- live model provider configuration, including any OpenAI-compatible NVIDIA gateway support
- mapping incident-generator evidence into CrisisMode's internal diagnosis model
- route selection and agent execution
- agent-specific recovery planning
- live or simulated tool execution semantics

This boundary keeps the benchmark harness stable while allowing CrisisMode internals to evolve.

## Definition Of Ready For Real Integration

CrisisMode support is ready to treat as a real integration when:

- the CrisisMode-owned adapter command passes strict compatibility scoring
- route accuracy is reported separately from diagnosis correctness
- negative cases prevent over-routing regressions
- v2 investigation-session failures are covered
- CI publishes readable failure output

Until then, incident-generator provides a solid compatibility target, but not proof of CrisisMode's end-to-end behavior.
