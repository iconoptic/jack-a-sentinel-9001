#!/usr/bin/env bash
# Install Espressif's esp_prov BLE provisioning client (used by sentinel-provision,
# Phase 4) without a full ESP-IDF toolchain.
#
# esp_prov loads generated protobuf modules from two places (see its proto/__init__.py):
#   $IDF_PATH/components/protocomm/python/*_pb2.py
#   <idf-extra-components>/network_provisioning/python/*_pb2.py
# This fetches only those directories plus the tool, at pinned refs. If a full ESP-IDF
# from install-esp-idf.sh is present, its protocomm files are reused.
#
# Python deps (bleak, cryptography, protobuf) are installed into the repo venv by
# scripts/setup-python-venv.sh.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
require_not_root
have git || die "git is required"

PROV_ROOT="$SENTINEL_DATA_DIR/esp-prov"
mkdir -p "$PROV_ROOT"

# fetch_sparse <dir> <url> <ref-or-sha> <pattern>...
fetch_sparse() {
  local dir="$1" url="$2" ref="$3"; shift 3
  if [[ -f "$dir/.sentinel-ref" && "$(cat "$dir/.sentinel-ref")" == "$ref" ]]; then
    ok "$(basename "$dir") already at $ref"
    return
  fi
  rm -rf "$dir"
  git init --quiet "$dir"
  git -C "$dir" remote add origin "$url"
  git -C "$dir" sparse-checkout set --no-cone "$@"
  git -C "$dir" fetch --quiet --depth 1 --filter=blob:none origin "$ref"
  git -C "$dir" checkout --quiet FETCH_HEAD
  printf '%s\n' "$ref" > "$dir/.sentinel-ref"
  ok "$(basename "$dir") at $ref"
}

# --- protocomm protobufs (IDF_PATH for esp_prov) ------------------------------
# shellcheck source=/dev/null
. "$SENTINEL_ENV_FILE" 2>/dev/null || true
if [[ -n "${SENTINEL_IDF_PATH:-}" && -d "$SENTINEL_IDF_PATH/components/protocomm/python" ]]; then
  PROV_IDF_PATH="$SENTINEL_IDF_PATH"
  info "Reusing full ESP-IDF at $PROV_IDF_PATH for protocomm protobufs"
else
  PROV_IDF_PATH="$PROV_ROOT/esp-idf-protocomm-$ESP_IDF_REF"
  info "Fetching ESP-IDF $ESP_IDF_REF protocomm protobufs (sparse)"
  fetch_sparse "$PROV_IDF_PATH" https://github.com/espressif/esp-idf.git "$ESP_IDF_REF" \
    '/components/protocomm/python/'
fi

# --- esp_prov tool + network_provisioning protobufs --------------------------
EXTRA_DIR="$PROV_ROOT/idf-extra-components"
info "Fetching network_provisioning tool + protobufs @ ${NETWORK_PROV_COMMIT:0:12}"
fetch_sparse "$EXTRA_DIR" https://github.com/espressif/idf-extra-components.git "$NETWORK_PROV_COMMIT" \
  '/network_provisioning/tool/' '/network_provisioning/python/'
ESP_PROV_DIR="$EXTRA_DIR/network_provisioning/tool/esp_prov"
[[ -f "$ESP_PROV_DIR/esp_prov.py" ]] || die "esp_prov.py not found under $ESP_PROV_DIR"

env_set SENTINEL_PROV_IDF_PATH "$PROV_IDF_PATH"
env_set SENTINEL_ESP_PROV_DIR "$ESP_PROV_DIR"

# --- Smoke test (needs the venv) ---------------------------------------------
VENV_PY="$REPO_ROOT/.venv/bin/python"
if [[ -x "$VENV_PY" ]]; then
  info "Verifying esp_prov imports with $VENV_PY"
  if IDF_PATH="$PROV_IDF_PATH" "$VENV_PY" "$ESP_PROV_DIR/esp_prov.py" --help >/dev/null 2>&1; then
    ok "esp_prov.py --help runs"
  else
    IDF_PATH="$PROV_IDF_PATH" "$VENV_PY" "$ESP_PROV_DIR/esp_prov.py" --help 2>&1 | tail -5 >&2 || true
    warn "esp_prov did not start; run scripts/setup-python-venv.sh, then re-run this script."
  fi
else
  warn "No .venv yet; run scripts/setup-python-venv.sh to install bleak/cryptography/protobuf."
fi

cat <<EOF

esp_prov is at $ESP_PROV_DIR
Run it (after '. $SENTINEL_ENV_FILE'):

    IDF_PATH="\$SENTINEL_PROV_IDF_PATH" .venv/bin/python "\$SENTINEL_ESP_PROV_DIR/esp_prov.py" --transport ble --sec_ver 2 ...
EOF
