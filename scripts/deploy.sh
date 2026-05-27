#!/usr/bin/env bash
set -euo pipefail

SRC="."
DST=""
DEPLOY_ROOT="${DEPLOY_ROOT:-/tmp/deploy/1iis}"

usage() {
  cat <<'EOF'
Usage: scripts/deploy.sh [-s SRC] -d USER@HOST

Build an artifact from SRC, upload it to USER@HOST, extract it under
/tmp/deploy/1iis/REPO, then run the repo's scripts/setup.sh remotely.

Options:
  -s, --src   Source repository path. Defaults to current directory.
  -d, --dst   SSH destination, e.g. onei@1.2.3.4. Required.
  -h, --help  Show this help.
EOF
}

log() {
  printf '==> %s\n' "$*"
}

fail() {
  echo "error: $*" >&2
  exit 1
}

parse_args() {
  while [ "$#" -gt 0 ]; do
    case "$1" in
      -s|--src)
        [ "$#" -ge 2 ] || fail "$1 requires a value"
        SRC="$2"
        shift 2
        ;;
      -d|--dst)
        [ "$#" -ge 2 ] || fail "$1 requires a value"
        DST="$2"
        shift 2
        ;;
      -h|--help)
        usage
        exit 0
        ;;
      *)
        fail "unknown argument: $1"
        ;;
    esac
  done

  [ -n "$DST" ] || fail "missing required -d|--dst"
}

abs_path() {
  python3 -c 'from pathlib import Path; import sys; print(Path(sys.argv[1]).resolve())' "$1"
}

make_artifact() {
  local src="$1"
  local repo="$2"
  local artifact="$3"

  log "Creating artifact: $artifact"
  tar \
    --create \
    --gzip \
    --file "$artifact" \
    --owner=0 \
    --group=0 \
    --numeric-owner \
    --directory "$src" \
    --exclude '.git' \
    --exclude '.ipynb_checkpoints' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude 'tmp*' \
    --transform "s,^,${repo}/," \
    .
}

write_runner() {
  local runner="$1"

  cat >"$runner" <<'EOF'
#!/usr/bin/env sh
set -eu

: "${REPO:?missing REPO}"
: "${DEPLOY_ROOT:?missing DEPLOY_ROOT}"

REMOTE_ARTIFACT="$DEPLOY_ROOT/$REPO.tar.gz"
REMOTE_SRC="$DEPLOY_ROOT/$REPO"

echo "==> Preparing remote source: $REMOTE_SRC"
rm -rf "$REMOTE_SRC"
mkdir -p "$REMOTE_SRC"
tar -xzf "$REMOTE_ARTIFACT" -C "$REMOTE_SRC" --strip-components=1

if [ ! -x "$REMOTE_SRC/scripts/setup.sh" ]; then
  chmod +x "$REMOTE_SRC/scripts/setup.sh"
fi

echo "==> Running setup.sh for: $REPO"
cd "$REMOTE_SRC"
./scripts/setup.sh
EOF
}

upload_payload() {
  local artifact="$1"
  local runner="$2"
  local remote_artifact="$3"
  local remote_runner="$4"

  log "Ensuring remote deploy root: $DST:$DEPLOY_ROOT"
  ssh "$DST" "mkdir -p '$DEPLOY_ROOT'"

  log "Uploading artifact and runner to: $DST:$DEPLOY_ROOT"
  scp "$artifact" "$DST:$remote_artifact"
  scp "$runner" "$DST:$remote_runner"
}

run_remote_setup() {
  local repo="$1"
  local remote_runner="$2"

  log "Running remote setup"
  ssh -t "$DST" "sudo env REPO='$repo' DEPLOY_ROOT='$DEPLOY_ROOT' sh '$remote_runner'"
}

main() {
  parse_args "$@"

  SRC="$(abs_path "$SRC")"
  [ -d "$SRC" ] || fail "source directory not found: $SRC"

  local repo
  repo="$(basename "$SRC")"
  local artifact
  artifact="$(mktemp -t "${repo}.XXXXXX.tar.gz")"
  local runner
  runner="$(mktemp -t "${repo}.runner.XXXXXX.sh")"
  local remote_artifact="$DEPLOY_ROOT/$repo.tar.gz"
  local remote_runner="$DEPLOY_ROOT/$repo.run.sh"

  trap "rm -f '$artifact' '$runner'" EXIT

  make_artifact "$SRC" "$repo" "$artifact"
  write_runner "$runner"
  upload_payload "$artifact" "$runner" "$remote_artifact" "$remote_runner"
  run_remote_setup "$repo" "$remote_runner"

  log "Deployment finished: $repo -> $DST"
}

main "$@"
