#!/usr/bin/env bash
# Arch Linux dev machine: firmware build + flash, bench testing, host-code tests.
# (Roles: docs/phases/CONTRACTS.md "Development machines".)
#
#   scripts/install-arch.sh             # packages, serial access, ESP-IDF, venv, esp_prov
#   scripts/install-arch.sh --sync      # also full system upgrade first (pacman -Syu)
#   scripts/install-arch.sh --no-idf    # skip ESP-IDF (e.g. host-code work only)
#   scripts/install-arch.sh -y          # don't prompt
#
# One click from a bare machine to flashed cameras (the Fedora host must already be installed,
# because it generates the secrets and owns the hidden AP):
#   scripts/install-arch.sh --flash all --from you@fedora-host
#
#   --flash a|b|c|all   after installing, build and flash cameras via scripts/install-esp32.sh
#   --from USER@HOST    pull the camera secrets from the Fedora host first (needs SSH access)
#
# Idempotent: re-running only fills in what's missing.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
require_not_root

SYNC=0 WITH_IDF=1 WITH_PROV=1 FLASH="" FROM=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --sync)       SYNC=1 ;;
    --no-idf)     WITH_IDF=0 ;;
    --no-esp-prov) WITH_PROV=0 ;;
    --flash)      FLASH="${2:?--flash needs a|b|c|all}"; shift ;;
    --from)       FROM="${2:?--from needs user@host}"; shift ;;
    -y|--yes)     export ASSUME_YES=1 ;;
    -h|--help)    sed -n '2,17p' "$0"; exit 0 ;;
    *)            die "Unknown option: $1 (see --help)" ;;
  esac
  shift
done

. /etc/os-release
[[ "${ID:-}" == arch || " ${ID_LIKE:-} " == *" arch "* ]] || die "This is for Arch-based systems (found ID=${ID:-?})."
have pacman || die "pacman not found"

PACKAGES=(
  # ESP-IDF prerequisites (docs/vendor/esp-idf/.../linux-macos-setup-legacy.rst + EIM prerequisites)
  gcc git make flex bison gperf python python-pip cmake ninja ccache dfu-util libusb libffi openssl wget
  # ESP-IDF Linux-target host tests (Phase 3 unit tests)
  libbsd
  # Repo tooling: fetch-docs, datasheets, script linting
  curl jq poppler shellcheck
  # Bench: ffplay for /stream, mosquitto_sub/pub for MQTT checks (broker service stays disabled)
  ffmpeg mosquitto
  # BLE: watch cameras advertise / stop advertising (bluetoothctl)
  bluez bluez-utils
)

# --- System packages ---------------------------------------------------------
PACMAN_OPTS=(--needed)
[[ "${ASSUME_YES:-0}" == 1 ]] && PACMAN_OPTS+=(--noconfirm)
missing=()
for p in "${PACKAGES[@]}"; do pacman -Qq "$p" >/dev/null 2>&1 || missing+=("$p"); done
if [[ $SYNC == 1 ]]; then
  info "Full system upgrade + packages (pacman -Syu)"
  sudo pacman -Syu "${PACMAN_OPTS[@]}" "${PACKAGES[@]}"
elif ((${#missing[@]})); then
  info "Installing: ${missing[*]}"
  sudo pacman -S "${PACMAN_OPTS[@]}" "${missing[@]}" \
    || die "pacman failed. If it was a 404 / outdated mirror, re-run with --sync (Arch doesn't support partial upgrades)."
else
  ok "All ${#PACKAGES[@]} packages already installed"
fi

# --- Serial port access (CH340 -> /dev/ttyUSB*, native USB -> /dev/ttyACM*) ---
NEED_RELOGIN=0
if user_in_group uucp; then
  ok "$USER is in 'uucp' (serial ports)"
else
  info "Adding $USER to 'uucp' for /dev/ttyUSB* and /dev/ttyACM* access"
  sudo usermod -aG uucp "$USER"
  NEED_RELOGIN=1
fi

# --- ESP-IDF, venv, esp_prov, docs -------------------------------------------
[[ $WITH_IDF == 1 ]] && "$REPO_ROOT/scripts/install-esp-idf.sh"
"$REPO_ROOT/scripts/setup-python-venv.sh"
[[ $WITH_PROV == 1 ]] && "$REPO_ROOT/scripts/install-esp-prov.sh"
if [[ ! -f "$REPO_ROOT/docs/vendor/VERSIONS.tsv" ]]; then
  info "Fetching vendored docs"
  "$REPO_ROOT/scripts/fetch-docs.sh" >/dev/null && ok "docs/vendor/"
fi

# --- Camera secrets + optional flash -------------------------------------------
if [[ -n "$FROM" ]]; then
  "$REPO_ROOT/scripts/secrets-sync.sh" pull "$FROM" ${SENTINEL_REMOTE_REPO:+"$SENTINEL_REMOTE_REPO"}
fi
if [[ -n "$FLASH" ]]; then
  [[ $WITH_IDF == 1 ]] || die "--flash needs ESP-IDF (drop --no-idf)."
  [[ $NEED_RELOGIN == 0 ]] || { warn "Serial access needs a new login first. Log out/in, then run: scripts/install-esp32.sh $FLASH"; FLASH=""; }
fi
[[ -z "$FLASH" ]] || "$REPO_ROOT/scripts/install-esp32.sh" "$FLASH"

# --- Summary -----------------------------------------------------------------
echo
info "Arch dev machine ready."
[[ $NEED_RELOGIN == 1 ]] && warn "Log out and back in (or 'newgrp uucp') before flashing, for serial access."
if [[ -f "$SECRETS_DIR/ap.env" ]]; then
  cat <<EOF
Secrets are present in secrets/. Flash a camera (builds, bakes in its bind data, flashes; the
board reboots already bound, no BLE step):
    scripts/install-esp32.sh a        # then b, c   (or: all)
EOF
else
  cat <<EOF
Next: install the Fedora host (it generates the secrets and owns the hidden AP), then:
    scripts/install-esp32.sh all --from you@fedora-host
Phase 1 bench bring-up (own Wi-Fi, see firmware/bringup/README.md) needs no secrets:
    . scripts/idf-env.sh && cd firmware/bringup && cp -n wifi.local.example wifi.local
EOF
fi
