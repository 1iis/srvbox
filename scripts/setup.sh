#!/usr/bin/env bash
set -euo pipefail

REPO_URL="${SRVBOX_REPO_URL:-https://github.com/1iis/srvbox.git}"
DEST="${SRVBOX_DEST:-/opt/1iis/srvbox}"
BRANCH="${SRVBOX_BRANCH:-main}"
PYTHON="${PYTHON:-python3}"

log() {
  printf '==> %s\n' "$*"
}

need_root() {
  if [ "$(id -u)" -ne 0 ]; then
    echo "error: setup.sh must run as root" >&2
    exit 1
  fi
}

install_base_packages() {
  log "Ensuring base packages are installed"

  if command -v apt-get >/dev/null 2>&1; then
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y git python3 ca-certificates
  else
    echo "error: only apt-based systems are supported for now" >&2
    exit 1
  fi
}

clone_or_update_repo() {
  log "Ensuring srvbox repo exists at $DEST"

  mkdir -p "$(dirname "$DEST")"

  if [ -d "$DEST/.git" ]; then
    git -C "$DEST" fetch --depth=1 origin "$BRANCH"
    git -C "$DEST" checkout "$BRANCH"
    git -C "$DEST" reset --hard "origin/$BRANCH"
  else
    git clone --depth=1 --branch "$BRANCH" "$REPO_URL" "$DEST"
  fi
}

run_sync() {
  log "Handing off to host/sync.py"
  cd "$DEST"
  exec "$PYTHON" host/sync.py apply
}

main() {
  need_root
  install_base_packages
  clone_or_update_repo
  run_sync
}

main "$@"
