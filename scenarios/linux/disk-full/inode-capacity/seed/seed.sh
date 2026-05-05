#!/usr/bin/env bash
set -euo pipefail

source /sre-agent/harness/shared/linux-faults.sh
fault::fill_inodes /var/sre-agent 95
