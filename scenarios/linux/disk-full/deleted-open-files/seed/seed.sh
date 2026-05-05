#!/usr/bin/env bash
set -euo pipefail

source /sre-agent/harness/shared/linux-faults.sh
fault::deleted_open_file /var/sre-agent 240M 120
