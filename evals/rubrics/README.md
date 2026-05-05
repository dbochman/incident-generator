# Skill Rubrics

Phase 2 rubrics add a versioned scoring layer above fixture `expected.yaml`
checks. Tier 1 gates are deterministic and run in CI. Tier 2 criteria define an
LLM-judge contract that can execute when an explicit judge provider and model are
supplied. Default CI evals still leave Tier 2 in `defined_not_executed` mode.

Each eval manifest entry references one rubric. A fixture passes only when both
the fixture's deterministic expected checks and the rubric gates pass.
