#!/usr/bin/env bash

fault::cleanup_file() {
  echo "${SRE_AGENT_FAULT_CLEANUP_FILE:-/tmp/sre-agent-fault-cleanup.sh}"
}

fault::dry_run() {
  [[ "${SRE_AGENT_FAULT_DRY_RUN:-0}" == "1" ]]
}

fault::register_cleanup() {
  local command="$1"
  local file
  file="$(fault::cleanup_file)"
  umask 077
  mkdir -p "$(dirname "$file")"
  touch "$file"
  printf '%s\n' "$command" >> "$file"
}

fault::cleanup_all() {
  local file
  file="$(fault::cleanup_file)"
  [[ -f "$file" ]] || return 0
  awk '{a[NR]=$0} END{for(i=NR;i>0;i--)print a[i]}' "$file" | while IFS= read -r command; do
    [[ -n "$command" ]] || continue
    bash -c "$command" || true
  done
  : > "$file"
}

fault::require_cmd() {
  command -v "$1" >/dev/null 2>&1 || { echo "$1 is required" >&2; return 127; }
}

fault::fill_disk() {
  local mount="$1"
  local target_pct="$2"
  local file="$mount/.sre-agent-fill-$$"
  local chunk="${SRE_AGENT_FAULT_DISK_CHUNK:-128M}"
  local index=0
  [[ "$target_pct" =~ ^[0-9]+$ ]] || { echo "target_pct must be an integer" >&2; return 2; }
  fault::register_cleanup "rm -f '$file'.*"
  if fault::dry_run; then
    echo "dry-run fill_disk mount=$mount target_pct=$target_pct file=$file"
    return 0
  fi
  fault::require_cmd df
  fault::require_cmd fallocate
  while [[ "$(df -P "$mount" | awk 'NR==2 {gsub(/%/, "", $5); print $5}')" -lt "$target_pct" ]]; do
    fallocate -l "$chunk" "$file.$index"
    index=$((index + 1))
  done
}

fault::fill_inodes() {
  local mount="$1"
  local target_pct="$2"
  local dir="$mount/.sre-agent-inodes-$$"
  local index=0
  local max_files="${SRE_AGENT_FAULT_INODE_MAX_FILES:-20000}"
  [[ "$target_pct" =~ ^[0-9]+$ ]] || { echo "target_pct must be an integer" >&2; return 2; }
  [[ "$max_files" =~ ^[0-9]+$ ]] || { echo "SRE_AGENT_FAULT_INODE_MAX_FILES must be an integer" >&2; return 2; }
  fault::register_cleanup "rm -rf '$dir'"
  if fault::dry_run; then
    echo "dry-run fill_inodes mount=$mount target_pct=$target_pct dir=$dir max_files=$max_files"
    return 0
  fi
  fault::require_cmd df
  mkdir -p "$dir"
  while [[ "$(df -Pi "$mount" | awk 'NR==2 {gsub(/%/, "", $5); print $5}')" -lt "$target_pct" ]]; do
    : > "$dir/file.$index"
    index=$((index + 1))
    if [[ "$index" -ge "$max_files" ]]; then
      echo "failed to reach inode target ${target_pct}% within ${max_files} files" >&2
      return 1
    fi
  done
}

fault::deleted_open_file() {
  local mount="$1"
  local size="$2"
  local duration="${3:-120}"
  local file="$mount/.sre-agent-deleted-open-$$"
  [[ "$size" =~ ^[0-9]+[KMG]?$ ]] || { echo "size must be an integer with optional K/M/G suffix" >&2; return 2; }
  [[ "$duration" =~ ^[0-9]+$ ]] || { echo "duration must be seconds" >&2; return 2; }
  fault::register_cleanup "rm -f '$file'"
  if fault::dry_run; then
    fault::register_cleanup "true # deleted_open_file dry-run"
    echo "dry-run deleted_open_file mount=$mount size=$size duration=${duration}s file=$file"
    return 0
  fi
  fault::require_cmd fallocate
  bash -c '
    set -euo pipefail
    file="$1"
    size="$2"
    duration="$3"
    exec 3>"$file"
    rm -f "$file"
    fallocate -l "$size" "/proc/$$/fd/3"
    sleep "$duration"
  ' _ "$file" "$size" "$duration" &
  local pid="$!"
  fault::register_cleanup "kill '$pid' 2>/dev/null || true"
}

fault::cpu_hog() {
  local cores="$1"
  local duration="$2"
  [[ "$cores" =~ ^[0-9]+$ ]] || { echo "cores must be an integer" >&2; return 2; }
  [[ "$duration" =~ ^[0-9]+$ ]] || { echo "duration must be seconds" >&2; return 2; }
  if fault::dry_run; then
    fault::register_cleanup "true # cpu_hog dry-run"
    echo "dry-run cpu_hog cores=$cores duration=${duration}s"
    return 0
  fi
  fault::require_cmd stress-ng
  stress-ng --cpu "$cores" --timeout "${duration}s" --metrics-brief >/tmp/sre-agent-cpu-hog.log 2>&1 &
  local pid="$!"
  fault::register_cleanup "kill '$pid' 2>/dev/null || true"
}

fault::cpu_named_workers() {
  local command_prefix="$1"
  local count="$2"
  local duration="${3:-120}"
  local unique_names="${4:-0}"
  [[ "$command_prefix" =~ ^[A-Za-z0-9_.-]+$ ]] || { echo "command_prefix contains unsafe characters" >&2; return 2; }
  [[ "$count" =~ ^[0-9]+$ ]] || { echo "count must be an integer" >&2; return 2; }
  [[ "$duration" =~ ^[0-9]+$ ]] || { echo "duration must be seconds" >&2; return 2; }
  [[ "$unique_names" =~ ^[01]$ ]] || { echo "unique_names must be 0 or 1" >&2; return 2; }
  if fault::dry_run; then
    fault::register_cleanup "true # cpu_named_workers dry-run"
    echo "dry-run cpu_named_workers command_prefix=$command_prefix count=$count duration=${duration}s unique_names=$unique_names"
    return 0
  fi
  fault::require_cmd yes
  local yes_bin
  yes_bin="$(command -v yes)"
  local index name link pid
  for index in $(seq 1 "$count"); do
    if [[ "$unique_names" == "1" ]]; then
      name="${command_prefix}${index}"
    else
      name="$command_prefix"
    fi
    link="/tmp/$name"
    ln -sf "$yes_bin" "$link"
    fault::register_cleanup "rm -f '$link'"
    "$link" >/dev/null &
    pid="$!"
    fault::register_cleanup "kill '$pid' 2>/dev/null || true"
  done
  (
    sleep "$duration"
    pkill -f "/tmp/${command_prefix}" 2>/dev/null || true
  ) &
  pid="$!"
  fault::register_cleanup "kill '$pid' 2>/dev/null || true"
}

fault::memory_pressure() {
  local mb="$1"
  local duration="${2:-60}"
  [[ "$mb" =~ ^[0-9]+$ ]] || { echo "mb must be an integer" >&2; return 2; }
  [[ "$duration" =~ ^[0-9]+$ ]] || { echo "duration must be seconds" >&2; return 2; }
  if fault::dry_run; then
    fault::register_cleanup "true # memory_pressure dry-run"
    echo "dry-run memory_pressure mb=$mb duration=${duration}s"
    return 0
  fi
  fault::require_cmd stress-ng
  stress-ng --vm 1 --vm-bytes "${mb}M" --timeout "${duration}s" --metrics-brief >/tmp/sre-agent-memory-pressure.log 2>&1 &
  local pid="$!"
  fault::register_cleanup "kill '$pid' 2>/dev/null || true"
}

fault::cgroup_memory_limit_bytes() {
  local value=""
  if [[ -f /sys/fs/cgroup/memory.max ]]; then
    value="$(cat /sys/fs/cgroup/memory.max)"
    if [[ "$value" != "max" && "$value" =~ ^[0-9]+$ ]]; then
      echo "$value"
      return 0
    fi
  fi
  if [[ -f /sys/fs/cgroup/memory/memory.limit_in_bytes ]]; then
    value="$(cat /sys/fs/cgroup/memory/memory.limit_in_bytes)"
    if [[ "$value" =~ ^[0-9]+$ && "$value" -lt 9223372036854771712 ]]; then
      echo "$value"
      return 0
    fi
  fi
  awk '/MemTotal:/ {print $2 * 1024}' /proc/meminfo
}

fault::cgroup_memory_current_bytes() {
  if [[ -f /sys/fs/cgroup/memory.current ]]; then
    cat /sys/fs/cgroup/memory.current
    return 0
  fi
  if [[ -f /sys/fs/cgroup/memory/memory.usage_in_bytes ]]; then
    cat /sys/fs/cgroup/memory/memory.usage_in_bytes
    return 0
  fi
  awk '/MemTotal:/ {total=$2} /MemAvailable:/ {avail=$2} END {print (total - avail) * 1024}' /proc/meminfo
}

fault::memory_target_mib() {
  local percent="$1"
  local limit_bytes limit_mib target_mib max_mib
  [[ "$percent" =~ ^[0-9]+$ ]] || { echo "percent must be an integer" >&2; return 2; }
  limit_bytes="$(fault::cgroup_memory_limit_bytes)"
  limit_mib=$((limit_bytes / 1024 / 1024))
  max_mib="${SRE_AGENT_FAULT_MEMORY_MAX_MB:-512}"
  [[ "$max_mib" =~ ^[0-9]+$ ]] || { echo "SRE_AGENT_FAULT_MEMORY_MAX_MB must be an integer" >&2; return 2; }
  if [[ "$limit_mib" -gt "$max_mib" ]]; then
    limit_mib="$max_mib"
  fi
  target_mib=$((limit_mib * percent / 100))
  if [[ "$target_mib" -lt 16 ]]; then
    target_mib=16
  fi
  echo "$target_mib"
}

fault::memory_pressure_percent() {
  local percent="$1"
  local duration="${2:-60}"
  local target_mib
  [[ "$duration" =~ ^[0-9]+$ ]] || { echo "duration must be seconds" >&2; return 2; }
  target_mib="$(fault::memory_target_mib "$percent")"
  if fault::dry_run; then
    fault::register_cleanup "true # memory_pressure_percent dry-run"
    echo "dry-run memory_pressure_percent percent=$percent target_mib=$target_mib duration=${duration}s"
    return 0
  fi
  fault::memory_pressure "$target_mib" "$duration"
}

fault::print_memory_summary() {
  local limit_bytes current_bytes total_mib used_mib available_mib
  limit_bytes="$(fault::cgroup_memory_limit_bytes)"
  current_bytes="$(fault::cgroup_memory_current_bytes)"
  total_mib=$((limit_bytes / 1024 / 1024))
  used_mib=$((current_bytes / 1024 / 1024))
  if [[ "$used_mib" -gt "$total_mib" ]]; then
    used_mib="$total_mib"
  fi
  available_mib=$((total_mib - used_mib))
  printf '              total        used        free      shared  buff/cache   available\n'
  printf 'Mem: %14d %11d %11d %11d %11d %11d\n' "$total_mib" "$used_mib" "$available_mib" 0 0 "$available_mib"
  printf 'Swap: %13d %11d %11d\n' 0 0 0
}

fault::print_top_memory_processes() {
  local limit_bytes limit_kib
  limit_bytes="$(fault::cgroup_memory_limit_bytes)"
  limit_kib=$((limit_bytes / 1024))
  printf 'PID USER %%CPU %%MEM RSS COMMAND\n'
  ps -eo pid=,user=,pcpu=,rss=,comm= --sort=-rss | head -10 | awk -v limit_kib="$limit_kib" '
    NF >= 5 {
      mem = limit_kib > 0 ? ($4 / limit_kib) * 100 : 0
      printf "%s %s %s %.1f %s %s\n", $1, $2, $3, mem, $4, $5
    }
  '
}

fault::clear_oom_events() {
  rm -f /var/sre-agent/oom-events.log
}

fault::record_oom_event() {
  local command="$1"
  local advisory="${2:-}"
  [[ "$command" =~ ^[A-Za-z0-9_.-]+$ ]] || { echo "command contains unsafe characters" >&2; return 2; }
  fault::register_cleanup "rm -f /var/sre-agent/oom-events.log"
  if fault::dry_run; then
    echo "dry-run record_oom_event command=$command"
    return 0
  fi
  mkdir -p /var/sre-agent
  {
    printf '[Mon May  4 00:00:00 2026] Out of memory: Killed process 8421 (%s) total-vm:524288kB, anon-rss:458752kB, file-rss:0kB, shmem-rss:0kB\n' "$command"
    printf '[Mon May  4 00:00:00 2026] oom-kill:constraint=CONSTRAINT_MEMCG,task=%s,pid=8421,uid=1001\n' "$command"
    if [[ -n "$advisory" ]]; then
      printf '[Mon May  4 00:00:01 2026] journalctl oom-kill advisory: %s\n' "$advisory"
    fi
  } > /var/sre-agent/oom-events.log
}

fault::print_oom_events() {
  cat /var/sre-agent/oom-events.log 2>/dev/null || true
}

fault::network_loss() {
  local iface="$1"
  local pct="$2"
  [[ "$iface" =~ ^[A-Za-z0-9_.:-]+$ ]] || { echo "iface contains unsafe characters" >&2; return 2; }
  [[ "$pct" =~ ^[0-9]+$ ]] || { echo "pct must be an integer" >&2; return 2; }
  fault::register_cleanup "tc qdisc del dev '$iface' root 2>/dev/null || true"
  if fault::dry_run; then
    echo "dry-run network_loss iface=$iface pct=$pct"
    return 0
  fi
  fault::require_cmd tc
  tc qdisc add dev "$iface" root netem loss "${pct}%"
}
