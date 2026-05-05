#!/usr/bin/env bash
set -euo pipefail

source /sre-agent/harness/shared/linux-faults.sh
export SRE_AGENT_FAULT_DISK_CHUNK="${SRE_AGENT_FAULT_DISK_CHUNK:-16M}"
fault::fill_disk /var/sre-agent 95
