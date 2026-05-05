#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: reset.sh <archetype>" >&2
  exit 2
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
archetype="$1"
template="$ROOT/sandbox-repos/archetypes/$archetype"
repo_env="SRE_AGENT_SANDBOX_REPO_${archetype^^}"
repo_env="${repo_env//-/_}"
repo_url="${!repo_env:-}"

[[ -d "$template" ]] || { echo "unknown sandbox archetype: $archetype" >&2; exit 2; }
[[ -n "$repo_url" ]] || { echo "set $repo_env to the sandbox repo clone URL" >&2; exit 2; }
command -v git >/dev/null 2>&1 || { echo "git is required" >&2; exit 127; }

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT
cp -R "$template/." "$workdir/"
git -C "$workdir" init --initial-branch=main >/dev/null
git -C "$workdir" add .
git -C "$workdir" -c user.name="sre-agent-reset" -c user.email="sre-agent-reset@example.invalid" commit -m "Reset $archetype sandbox" >/dev/null
git -C "$workdir" remote add sandbox-reset "$repo_url"
git -C "$workdir" push sandbox-reset main --force
