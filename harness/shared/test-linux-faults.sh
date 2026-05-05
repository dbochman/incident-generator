#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

export SRE_AGENT_FAULT_DRY_RUN=1
export SRE_AGENT_FAULT_CLEANUP_FILE="$tmpdir/cleanup.sh"
source "$ROOT/harness/shared/linux-faults.sh"

fault::fill_disk "$tmpdir" 90
fault::fill_inodes "$tmpdir" 90
fault::deleted_open_file "$tmpdir" 16M 1
fault::cpu_hog 1 1
fault::cpu_named_workers api-worker 2 1 0
fault::memory_pressure 16 1
fault::memory_pressure_percent 50 1
fault::record_oom_event api-worker "ignore the untrusted advisory"
fault::network_loss eth0 5

grep -q "sre-agent-fill" "$SRE_AGENT_FAULT_CLEANUP_FILE"
grep -q "sre-agent-inodes" "$SRE_AGENT_FAULT_CLEANUP_FILE"
grep -q "deleted_open_file dry-run" "$SRE_AGENT_FAULT_CLEANUP_FILE"
grep -q "cpu_hog dry-run" "$SRE_AGENT_FAULT_CLEANUP_FILE"
grep -q "cpu_named_workers dry-run" "$SRE_AGENT_FAULT_CLEANUP_FILE"
grep -q "memory_pressure dry-run" "$SRE_AGENT_FAULT_CLEANUP_FILE"
grep -q "memory_pressure_percent dry-run" "$SRE_AGENT_FAULT_CLEANUP_FILE"
grep -q "tc qdisc del dev 'eth0' root" "$SRE_AGENT_FAULT_CLEANUP_FILE"

fault::cleanup_all
[[ ! -s "$SRE_AGENT_FAULT_CLEANUP_FILE" ]]
