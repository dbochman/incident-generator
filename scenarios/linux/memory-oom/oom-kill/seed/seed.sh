#!/usr/bin/env bash
set -euo pipefail

source /sre-agent/harness/shared/linux-faults.sh

fault::clear_oom_events
fault::record_oom_event api-worker
fault::memory_pressure_percent "${SRE_AGENT_MEMORY_PRESSURE_PERCENT:-92}" "${SRE_AGENT_MEMORY_PRESSURE_DURATION:-120}"
