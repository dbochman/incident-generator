# EKS Staging Terraform

Expected operator flow:

1. Provision an AWS account or sandbox project with budget alerts.
2. Export AWS credentials scoped to EKS, EC2, IAM, and CloudWatch resources for
   the sandbox account only.
3. Set a unique `run_id` for every scenario run.
4. Apply, run the scenario, then destroy immediately.

The module is a starting point for Phase A W5. It avoids persistent stateful
dependencies and tags every resource with `sre-agent-phase-a=true`.
