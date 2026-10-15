#!/usr/bin/env bash
# Move the secrets the cameras need between machines, over SSH, without ever writing a
# bundle to disk. The Fedora host is authoritative: it generates the secrets and owns the AP.
# The Arch/dev machine only needs ap.env + cameras/*.env to flash boards.
#
#   scripts/secrets-sync.sh pull user@fedora-host [REMOTE_REPO]   # fetch camera secrets
#   scripts/secrets-sync.sh pull --full user@fedora-host [REMOTE_REPO]   # whole secrets/ tree
#   scripts/secrets-sync.sh export [--full]    # tar to stdout (pipe it over ssh yourself)
#   scripts/secrets-sync.sh import             # tar from stdin
#
# REMOTE_REPO defaults to the same path as this checkout. Import refuses to overwrite a
# different SSID/PSK unless --force, since that would orphan every flashed camera.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
umask 077

FULL=0 FORCE=0
args=()
for a in "$@"; do
  case "$a" in
    --full)  FULL=1 ;;
    --force) FORCE=1 ;;
    -h|--help) sed -n '2,13p' "$0"; exit 0 ;;
    *) args+=("$a") ;;
  esac
done
set -- "${args[@]}"
cmd="${1:-}"; shift || true

do_export() {
  [[ -f "$SECRETS_DIR/ap.env" ]] || die "No $SECRETS_DIR/ap.env here. Run scripts/install-fedora.sh on the host first."
  if [[ $FULL == 1 ]]; then
    tar -C "$REPO_ROOT" -cf - secrets
  else
    local files=(secrets/ap.env)
    for f in "$SECRETS_DIR"/cameras/*.env; do [[ -f "$f" ]] && files+=("secrets/cameras/$(basename "$f")"); done
    tar -C "$REPO_ROOT" -cf - "${files[@]}"
  fi
}

do_import() {
  local stage
  stage="$(mktemp -d)"
  trap 'rm -rf "$stage"' RETURN
  tar -C "$stage" -xf - --no-same-owner --no-same-permissions
  [[ -f "$stage/secrets/ap.env" ]] || die "Bundle has no secrets/ap.env"
  # Only accept paths we know about: tar from a remote host is untrusted input.
  while IFS= read -r f; do
    case "$f" in
      secrets|secrets/|secrets/ap.env|secrets/cameras|secrets/cameras/|secrets/cameras/[abc].env) ;;
      secrets/frigate.env|secrets/mosquitto|secrets/mosquitto/*|secrets/digests.txt|secrets/frigate-admin.txt) ;;
      *) die "Unexpected path in bundle: $f" ;;
    esac
  done < <(cd "$stage" && find secrets \( -type f -o -type d \))
  [[ -z "$(cd "$stage" && find secrets -type l)" ]] || die "Bundle contains symlinks"

  if [[ -f "$SECRETS_DIR/ap.env" && $FORCE != 1 ]]; then
    local old_ssid old_psk new_ssid new_psk
    old_ssid="$(ap_env_get SSID)"; old_psk="$(ap_env_get PSK)"
    new_ssid="$(kv_get "$stage/secrets/ap.env" SSID)"
    new_psk="$(kv_get "$stage/secrets/ap.env" PSK)"
    if [[ -n "$old_ssid" && ( "$old_ssid" != "$new_ssid" || "$old_psk" != "$new_psk" ) ]]; then
      die "This machine already has a different AP SSID/PSK. Re-run with --force to replace it
    (cameras flashed with the old values must be reflashed)."
    fi
  fi
  mkdir -p "$SECRETS_DIR"
  chmod 700 "$SECRETS_DIR"
  cp -a "$stage/secrets/." "$SECRETS_DIR/"
  find "$SECRETS_DIR" -type d -exec chmod 700 {} +
  find "$SECRETS_DIR" -type f -exec chmod 600 {} +
  ok "Imported into $SECRETS_DIR"
}

case "$cmd" in
  export) do_export ;;
  import) do_import ;;
  pull)
    remote="${1:-}"; [[ -n "$remote" ]] || die "usage: $0 pull [--full] user@host [REMOTE_REPO]"
    remote_repo="${2:-$REPO_ROOT}"
    full_flag=""; [[ $FULL == 1 ]] && full_flag="--full"
    info "Fetching secrets from $remote:$remote_repo"
    # shellcheck disable=SC2029  # remote_repo is expanded locally on purpose
    ssh "$remote" "cd $(printf '%q' "$remote_repo") && scripts/secrets-sync.sh export $full_flag" | do_import
    ;;
  *) sed -n '2,13p' "$0"; exit 1 ;;
esac
