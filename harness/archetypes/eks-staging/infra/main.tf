terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.region
}

locals {
  cluster_name = "sre-agent-phase-a-${var.run_id}"
  common_tags = merge(
    {
      "sre-agent-phase-a" = "true"
      "sre-agent-run-id"  = var.run_id
    },
    var.tags,
  )
}

resource "aws_vpc" "this" {
  cidr_block           = "10.42.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true
  tags                 = merge(local.common_tags, { Name = "${local.cluster_name}-vpc" })

  lifecycle {
    precondition {
      condition     = var.run_id != ""
      error_message = "run_id must be unique and non-empty."
    }
  }
}

# The rest of the EKS module is intentionally left for the cloud-account unlock:
# subnets, IAM roles, the EKS control plane, a 1-node managed nodegroup, and
# Helm-based observability installation are created in the same run and destroyed
# after the scenario exits.
