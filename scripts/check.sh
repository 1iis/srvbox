#!/usr/bin/env bash
set -euo pipefail

log() {
  printf '==> %s\n' "$*"
}

ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"

cd "$ROOT"

log "Checking shell scripts"
for script in scripts/*.sh; do
  bash -n "$script"
done

log "Checking Python syntax"
python3 -m py_compile host/sync.py

log "Checking sync status command"
python3 host/sync.py status

log "All checks passed"
