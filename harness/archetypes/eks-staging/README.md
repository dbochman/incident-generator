# EKS Staging Archetype

This archetype is the Phase A cloud-fidelity target. It is intentionally last in
the sequence because it depends on AWS account, IAM, and billing guardrail
approval. The Terraform module refuses to reuse a non-owned cluster name and is
designed for create-run-destroy workflows.
