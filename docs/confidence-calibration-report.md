# Confidence Calibration Report

`python3 -m incident_generator confidence-calibration --json` renders the checked confidence calibration snapshot for benchmark entrants. The report compares deterministic skill-agent baselines against recorded live LLM skill-agent observations across low, medium, and high evidence-quality buckets.

The default definition is `harness/confidence-calibration-report.yaml`. It records:

- evidence quality policy for `low`, `medium`, and `high` cases;
- required agents: `deterministic` and `live_llm_snapshot`;
- selected fixture cases, expected hypotheses, target confidence, and allowed confidence ranges;
- recorded live snapshot provenance for `aws/anthropic/bedrock-claude-opus-4-6` with separate-family `openai/openai/gpt-5.5` Tier 2 judging.

The package command validates paths, expected hypotheses, required agents, live-provider call markers, Tier 2 status, and confidence ranges. In the canonical repo, `tools/render_confidence_calibration_report.py` also verifies the checked observations against the live LLM smoke Markdown snapshots and renders `docs/confidence-calibration-report.md`.
