# EKS Staging Archetype

This archetype is the planned cloud-fidelity target. It is intentionally blocked
in the runner until AWS account, IAM, budget, and teardown guardrails are
implemented and approved.

Current state:

- Terraform scaffolding exists under `infra/`.
- Resource names are intended to be run-scoped through `run_id`.
- Runner dispatch currently returns a blocked result for `eks-staging`.

Before this archetype is enabled, the production roadmap requires sandbox-only
credentials, budget alerts, region and account allowlists, create-run-destroy
runbooks, and verified cleanup after partial failure.
