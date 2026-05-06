# Evidence Signal Role Taxonomy

`harness/evidence-signal-role-taxonomy.yaml` defines internal evidence labels for noisy benchmark renderers, rubrics, and benchmark result summaries. Labels are never agent-visible.

| Role | Meaning |
| --- | --- |
| `causal` | Incident-injector evidence that can directly satisfy or falsify the expected hypothesis. |
| `contextual` | Workload, topology, timing, and service metadata needed to interpret causal evidence. |
| `ambient` | Bounded production-like background signals from `harness/production-noise-source-catalog.yaml`. |
| `red_herring` | Plausible but non-causal evidence used to test evidence discipline. |
| `hostile` | Untrusted text that attempts to steer the agent or trigger forbidden actions. |

Renderers may store `source_id`, `signal_role`, `score_weight`, and `expected_hypothesis_link` in internal manifests, rubric traces, and benchmark summaries. `incident_generator noisy-fixture` stores these labels under `internal` and strips them from `agent_visible` chunks. Prompt-rendered evidence chunks, provider output, skill-agent input bundles, and raw operator evidence must also omit the labels unless the artifact is explicitly internal.
