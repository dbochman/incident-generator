#!/usr/bin/env bash
set -euo pipefail

source /sre-agent/harness/shared/linux-faults.sh
fault::cleanup_all
fault::clear_oom_events
