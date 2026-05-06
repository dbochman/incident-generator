#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${SRE_AGENT_APP_HOST_ROOT:-/var/sre-agent/app-host-lite}"
RUN_DIR="${SRE_AGENT_APP_HOST_RUN_DIR:-/run/sre-agent/app-host-lite}"
LOG_DIR="${SRE_AGENT_APP_HOST_LOG_DIR:-/var/log/sre-agent/app-host-lite}"
JOURNAL_DIR="${SRE_AGENT_APP_HOST_JOURNAL_DIR:-/var/log/journal/sre-agent}"
TMP_DIR="${SRE_AGENT_APP_HOST_TMP_DIR:-/tmp/sre-agent-app-host-lite}"

HEALTH_INTERVAL="${SRE_AGENT_APP_HOST_HEALTH_INTERVAL:-5}"
LOG_ROTATE_BYTES="${SRE_AGENT_APP_HOST_LOG_ROTATE_BYTES:-16384}"
LOG_ROTATE_KEEP="${SRE_AGENT_APP_HOST_LOG_ROTATE_KEEP:-3}"
TEMP_KEEP_FILES="${SRE_AGENT_APP_HOST_TEMP_KEEP_FILES:-24}"
DATA_FILES="${SRE_AGENT_APP_HOST_DATA_FILES:-8}"
DATA_KIB="${SRE_AGENT_APP_HOST_DATA_KIB:-8}"
CPU_LOAD="${SRE_AGENT_APP_HOST_CPU_LOAD:-3}"
MEMORY_MB="${SRE_AGENT_APP_HOST_MEMORY_MB:-12}"

children=()

mkdir -p "$APP_ROOT/data" "$RUN_DIR" "$LOG_DIR" "$JOURNAL_DIR" "$TMP_DIR"
printf '%s\n' "$$" > "$RUN_DIR/supervisor.pid"
: > "$RUN_DIR/workers"

cleanup() {
  local pid
  for pid in "${children[@]:-}"; do
    kill "$pid" 2>/dev/null || true
  done
  for pid in "${children[@]:-}"; do
    wait "$pid" 2>/dev/null || true
  done
}

trap cleanup TERM INT EXIT

write_journal() {
  local message="$1"
  printf 'REALTIME_TIMESTAMP=%s\nSYSLOG_IDENTIFIER=app-host-lite\nMESSAGE=%s\n\n' \
    "$(date +%s)" "$message" >> "$JOURNAL_DIR/app-host-lite.journal"
}

heartbeat_loop() {
  while true; do
    date +%s > "$RUN_DIR/health"
    printf '%s level=info service=app-host-lite event=health status=ok worker=checkout-host\n' \
      "$(date --iso-8601=seconds)" >> "$LOG_DIR/app.log"
    write_journal "app-host-lite health status ok"
    sleep "$HEALTH_INTERVAL"
  done
}

rotate_logs_loop() {
  local size index previous next
  while true; do
    if [[ -f "$LOG_DIR/app.log" ]]; then
      size="$(wc -c < "$LOG_DIR/app.log")"
      if [[ "$size" -gt "$LOG_ROTATE_BYTES" ]]; then
        for ((index = LOG_ROTATE_KEEP - 1; index >= 1; index--)); do
          previous="$LOG_DIR/app.log.$index"
          next="$LOG_DIR/app.log.$((index + 1))"
          [[ -f "$previous" ]] && mv "$previous" "$next"
        done
        mv "$LOG_DIR/app.log" "$LOG_DIR/app.log.1"
        : > "$LOG_DIR/app.log"
        write_journal "app-host-lite rotated application log"
      fi
    fi
    sleep 3
  done
}

temp_file_churn_loop() {
  local file
  while true; do
    file="$TMP_DIR/tmp-$(date +%s%N)"
    dd if=/dev/zero of="$file" bs=1024 count=4 status=none 2>/dev/null || true
    find "$TMP_DIR" -maxdepth 1 -type f -name 'tmp-*' -printf '%T@ %p\n' \
      | sort -rn \
      | awk -v keep="$TEMP_KEEP_FILES" 'NR > keep {print $2}' \
      | xargs -r rm -f
    sleep 2
  done
}

disk_write_loop() {
  local counter=0
  local file
  while true; do
    file="$APP_ROOT/data/chunk-$((counter % DATA_FILES)).dat"
    dd if=/dev/zero of="$file" bs=1024 count="$DATA_KIB" conv=notrunc status=none 2>/dev/null || true
    printf '%s level=info service=app-host-lite event=cache_refresh bytes=%s file=%s\n' \
      "$(date --iso-8601=seconds)" "$((DATA_KIB * 1024))" "$(basename "$file")" >> "$LOG_DIR/app.log"
    counter=$((counter + 1))
    sleep 4
  done
}

service_noise_loop() {
  while true; do
    printf '%s level=warn service=app-host-lite event=http_request method=GET path=/favicon.ico status=404 benign=true\n' \
      "$(date --iso-8601=seconds)" >> "$LOG_DIR/app.log"
    printf '%s level=info service=app-host-lite event=dependency_retry dependency=metadata-cache attempt=1 result=success\n' \
      "$(date --iso-8601=seconds)" >> "$LOG_DIR/app.log"
    write_journal "app-host-lite benign service noise emitted"
    sleep 11
  done
}

background_pressure_loop() {
  while true; do
    if command -v stress-ng >/dev/null 2>&1; then
      stress-ng \
        --cpu 1 \
        --cpu-load "$CPU_LOAD" \
        --vm 1 \
        --vm-bytes "${MEMORY_MB}M" \
        --timeout 2s \
        --quiet >/dev/null 2>&1 || true
    fi
    sleep 8
  done
}

start_worker() {
  local name="$1"
  shift
  "$@" &
  local pid="$!"
  children+=("$pid")
  printf '%s %s\n' "$name" "$pid" >> "$RUN_DIR/workers"
}

start_worker heartbeat heartbeat_loop
start_worker log-rotation rotate_logs_loop
start_worker temp-file-churn temp_file_churn_loop
start_worker disk-writes disk_write_loop
start_worker service-noise service_noise_loop
start_worker background-pressure background_pressure_loop

wait -n "${children[@]}"
