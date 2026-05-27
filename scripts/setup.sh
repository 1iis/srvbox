#!/usr/bin/env bash
set -euo pipefail

APP="${APP:-srvbox}"
BASE="${BASE:-/opt/1iis}"
APP_ROOT="${APP_ROOT:-$BASE/$APP}"
RELEASES="$APP_ROOT/releases"
CURRENT="$APP_ROOT/current"
PYTHON="${PYTHON:-python3}"

log() {
  printf '==> %s\n' "$*"
}

fail() {
  echo "error: $*" >&2
  exit 1
}

need_root() {
  if [ "$(id -u)" -ne 0 ]; then
    fail "setup.sh must run as root"
  fi
}

source_dir() {
  cd "$(dirname "$0")/.."
  pwd -P
}

install_base_packages() {
  log "Ensuring base packages are installed"

  if command -v apt-get >/dev/null 2>&1; then
    apt-get update
    DEBIAN_FRONTEND=noninteractive apt-get install -y python3 ca-certificates
  else
    fail "only apt-based systems are supported for now"
  fi
}

copy_release() {
  local src="$1"
  local stamp
  stamp="$(date -u +%Y%m%dT%H%M%SZ)"
  local release="$RELEASES/$stamp"
  local tmp="$release.tmp"

  log "Installing $APP release: $release"
  mkdir -p "$RELEASES"
  chown root:root "$APP_ROOT" "$RELEASES"
  chmod 0755 "$APP_ROOT" "$RELEASES"
  rm -rf "$tmp"
  mkdir -p "$tmp"

  tar \
    --create \
    --file - \
    --directory "$src" \
    --exclude '.git' \
    --exclude '.ipynb_checkpoints' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude 'tmp*' \
    . | tar --extract --file - --directory "$tmp"

  chown -R root:root "$tmp"
  chmod -R u=rwX,go=rX "$tmp"
  chmod +x "$tmp"/scripts/*.sh

  mv "$tmp" "$release"
  ln -sfn "$release" "$CURRENT"
}

run_sync() {
  log "Handing off to host/sync.py"
  cd "$CURRENT"
  exec "$PYTHON" host/sync.py apply
}

main() {
  need_root

  local src
  src="$(source_dir)"

  install_base_packages
  copy_release "$src"
  run_sync
}

main "$@"
