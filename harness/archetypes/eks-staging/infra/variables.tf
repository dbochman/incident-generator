variable "region" {
  type    = string
  default = "us-east-1"
}

variable "run_id" {
  description = "Unique run identifier; reused values are treated as stale cluster risk."
  type        = string
}

variable "cluster_version" {
  type    = string
  default = "1.29"
}

variable "node_instance_type" {
  type    = string
  default = "t3.medium"
}

variable "tags" {
  type    = map(string)
  default = {}
}
