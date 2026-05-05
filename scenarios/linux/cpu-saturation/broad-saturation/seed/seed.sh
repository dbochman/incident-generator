#!/usr/bin/env bash
set -euo pipefail

source /sre-agent/harness/shared/linux-faults.sh
cpu_count="$(nproc)"
default_workers=$((cpu_count > 1 ? cpu_count - 1 : 1))
workers="${SRE_AGENT_CPU_WORKERS:-$default_workers}"
fault::cpu_named_workers cpu-worker "$workers" 120 1
