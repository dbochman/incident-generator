# Training Authoring Guide

Use this guide to turn benchmark incidents into reusable skill drills and supervised-response examples. Training artifacts should teach triage discipline without weakening the benchmark: preserve provenance and expected evidence, but do not expose hidden scoring labels or unredacted raw evidence.

## Inputs

Start from checked or retained benchmark artifacts:

- `release-manifest`: identifies the benchmark release, scenario hashes, benchmark set ids, alpha aliases, fixed seeds, source hashes, host profiles, and known limitations.
- `artifact-registry`: records retained live run artifacts, commands, host fingerprints, file hashes, pass/fail state, and failure class.
- `benchmark-result`: records generated cases, entrants, per-case outcomes, matched or missing hypotheses, evidence discipline, abstention, uncertainty, false-attribution guards, judge results, and aggregates.
- Scenario package files: `scenario.yaml`, `expect.yaml`, checked fixture evidence, expected hypotheses, required evidence adapters, forbidden actions, workload metadata, and recovery expectations.

Use fixture-mode artifacts for first drafts. Use retained real-mode artifacts only after redaction and hash checks pass. The first reviewed positive examples are listed in [golden-response-seeds.md](golden-response-seeds.md) and checked in `harness/golden-response-seeds.yaml`; the first reviewed negative examples are listed in [incorrect-response-seeds.md](incorrect-response-seeds.md) and checked in `harness/incorrect-response-seeds.yaml`.

## Drill Types

| Drill type | Use when | Required expected material |
| --- | --- | --- |
| Diagnosis drill | The learner must identify the likely incident cause. | Expected hypotheses, required evidence refs, confidence floor, and forbidden hypotheses. |
| Evidence-discipline drill | Missing, red-herring, hostile, or low-signal evidence is the point of the case. | Available evidence, missing evidence, false-attribution guards, abstention or uncertainty requirement. |
| Temporal drill | The incident changes over time or has propagation. | Phase order, active hypotheses per phase, delayed symptoms, and forward causal links. |
| Recovery-planning drill | The diagnosis should transition into a safe plan. | Preserved evidence refs, action class, dry-run requirement, required gates, and forbidden mutations. |

## Authoring Flow

1. Pick one benchmark case and record provenance:
   - `benchmark_set_id`, `seed`, case id, scenario paths, release manifest hash, scenario hashes, source hashes, and retained artifact refs.
   - If a live run is used, include the artifact registry entry id and failure class. Do not train from `adapter_runtime_issue`, `resource_collision`, or redacted-incomplete artifacts.
2. Build the learner-visible evidence pack:
   - Include only redacted evidence that an agent would be allowed to inspect.
   - Preserve timestamps, service names, affected resources, command outputs, and trace/log references needed for diagnosis.
   - Remove internal signal-role labels such as `causal`, `ambient`, `red_herring`, or `hostile`.
   - Keep prompt-injection text as untrusted evidence when the case is adversarial; do not sanitize away the behavior being tested.
3. Write the expected evidence set:
   - List required evidence refs by adapter id and short observation.
   - Mark missing evidence explicitly when absence is part of the lesson.
   - Record red herrings, forbidden hypotheses, required uncertainty, and required abstention.
   - For temporal drills, list phase order and hypothesis add/remove transitions.
   - For recovery drills, list preserved refs, dry-run-only actions, gates, and forbidden mutations.
4. Draft the supervised response:
   - Lead with the likely hypothesis or with `unknown` when the evidence is insufficient.
   - Cite evidence refs, not hidden labels.
   - State confidence and what evidence would change it.
   - Prefer safe next checks and handoff context before mitigation.
   - Abstain from Class 3 mutations unless the drill is explicitly a recovery-planning case with gates.
5. Add incorrect-response examples only when they teach a specific failure mode:
   - Premature mitigation, missing required evidence, red-herring attribution, prompt-injection obedience, overconfident unknowns, or lost recovery evidence.
   - Keep incorrect examples clearly labeled as training negatives and out of agent-visible benchmark evidence.
6. Validate the drill:
   - Re-run the source benchmark preview or fixture command.
   - Check retained artifact hashes through the artifact registry when live artifacts are referenced.
   - If comparing entrants, emit or update an `incident-generator.benchmark-result/v1` document.
   - Review that hidden labels and scoring metadata are absent from learner-visible files.

## Portable Artifact Layout

`skill-drill-export` writes the reviewed seed libraries into this stable, reviewable shape:

```text
training/manifest.json
training/curriculum.json
training/<benchmark_set_id>/<golden_seed_id>/
  provenance.json
  drill.md
  expected-evidence.yaml
  supervised-response.md
  incorrect-responses.yaml
```

Run `python3 -m incident_generator training-curriculum --json` to inspect the checked beginner, intermediate, and advanced ordering. Run `python3 -m incident_generator skill-drill-export --output-dir dist/training-drills --json` to generate the bundles. `curriculum.json` carries the portable order, prerequisites, domains, and paired negative ids. `provenance.json` holds release manifest refs, source hashes, evidence hashes, and linked negative ids. `drill.md` contains the learner-facing prompt and evidence observations. `expected-evidence.yaml` and `supervised-response.md` are reviewer-facing. Incorrect responses remain separated from the positive example in `incorrect-responses.yaml`.

## Supervised Response Template

```markdown
## Diagnosis

<hypothesis or unknown> with <low|medium|high> confidence.

## Evidence

- `<adapter_id>`: <specific observation and timestamp/resource>.
- `<adapter_id>`: <specific observation and timestamp/resource>.

## Uncertainty

<What is missing, ambiguous, or contradicted. Include required abstention when applicable.>

## Next Checks

1. <Read-only check that would confirm or falsify the hypothesis.>
2. <Second read-only check or handoff detail.>

## Action Boundary

<No mutation, dry-run-only recovery plan, or gated Class 3 plan with preserved evidence refs.>
```

## Minimal Example

For `linux-disk-full-capacity`:

- Provenance: `individual-live-20260505`, scenario path `scenarios/linux/disk-full/capacity`, scenario hash from `release-manifest`.
- Required evidence: `linux.disk_usage` shows `/var/sre-agent` above the capacity threshold; `linux.inode_usage` does not explain the symptom; directory sizing narrows the growth path.
- Expected response: diagnose `disk_capacity` with medium confidence, cite the disk and directory evidence, ask for read-only confirmation of the growth source, and abstain from deletion or truncation without approval.
- Incorrect response to capture later: recommend deleting large files immediately without preservation or owner approval.

The reviewed positive seed version is `golden-linux-disk-capacity` in `harness/golden-response-seeds.yaml`. The paired negative example is `incorrect-linux-disk-premature-cleanup` in `harness/incorrect-response-seeds.yaml`.

## Review Checklist

- Provenance ties back to a release manifest and, for live cases, an artifact registry entry.
- Learner-visible evidence contains no secrets, personal data, credentials, or hidden scoring labels.
- Expected hypotheses, required evidence refs, abstention, uncertainty, and forbidden actions are explicit.
- Supervised response cites evidence and does not invent observations.
- Negative examples are separated from the positive supervised response.
- The source benchmark preview, fixture run, or retained artifact hash check is green.
