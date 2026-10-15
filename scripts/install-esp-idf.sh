#!/usr/bin/env bash
# Install ESP-IDF (pinned in scripts/lib/versions.sh) for the camera firmware.
# Distro-neutral: run install-arch.sh / install-fedora.sh first for system packages.
#
# Uses the documented git-clone + install.sh method ("legacy" in v6 docs) rather than
# the EIM installer: it is pinnable, scriptable, and needs no third-party package repo.
# See docs/vendor/esp-idf/docs/en/get-started/linux-macos-setup-legacy.rst.
#
#   scripts/install-esp-idf.sh            # clone to ~/esp/esp-idf-<ref>, install esp32s3 tools
#   ESP_ROOT=/opt/esp scripts/install-esp-idf.sh
#   SENTINEL_PYTHON=/usr/bin/python3.13 scripts/install-esp-idf.sh
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
require_not_root

ESP_ROOT="${ESP_ROOT:-$HOME/esp}"
IDF_DIR="$ESP_ROOT/esp-idf-$ESP_IDF_REF"

have git || die "git is required"

# --- Python ------------------------------------------------------------------
PY="$(pick_python 10 "$PY_MAX_MINOR")" \
  || die "Need Python 3.10–3.$PY_MAX_MINOR with ssl+venv. Set SENTINEL_PYTHON=/path/to/python3.x"
info "Python for ESP-IDF: $PY ($("$PY" --version 2>&1))"

# ESP-IDF names its venv after the interpreter version and re-resolves `python3` on
# every export.sh. Pin `python3` through a shim dir so a later pyenv switch can't
# break the environment. scripts/idf-env.sh puts the same shim on PATH.
SHIM_DIR="$SENTINEL_DATA_DIR/idf-python-bin"
mkdir -p "$SHIM_DIR"
ln -sfn "$PY" "$SHIM_DIR/python3"
ln -sfn "$PY" "$SHIM_DIR/python"
export PATH="$SHIM_DIR:$PATH"

# --- Clone -------------------------------------------------------------------
if [[ -d "$IDF_DIR/.git" ]]; then
  have_ref="$(git -C "$IDF_DIR" describe --tags --exact-match 2>/dev/null || echo unknown)"
  [[ "$have_ref" == "$ESP_IDF_REF" ]] \
    || die "$IDF_DIR exists at '$have_ref', expected $ESP_IDF_REF. Move it aside and re-run."
  info "ESP-IDF $ESP_IDF_REF already cloned at $IDF_DIR"
  git -C "$IDF_DIR" submodule update --init --recursive --depth 1
else
  info "Cloning ESP-IDF $ESP_IDF_REF into $IDF_DIR (shallow, with submodules)"
  mkdir -p "$ESP_ROOT"
  git clone --branch "$ESP_IDF_REF" --depth 1 --recursive --shallow-submodules \
    https://github.com/espressif/esp-idf.git "$IDF_DIR"
fi

# --- Tools + Python env ------------------------------------------------------
info "Running install.sh $ESP_IDF_TARGETS (toolchains go to ${IDF_TOOLS_PATH:-$HOME/.espressif})"
(cd "$IDF_DIR" && ./install.sh "$ESP_IDF_TARGETS")

env_set SENTINEL_IDF_PATH "$IDF_DIR"
env_set SENTINEL_IDF_PYTHON_SHIM "$SHIM_DIR"
[[ -n "${IDF_TOOLS_PATH:-}" ]] && env_set IDF_TOOLS_PATH "$IDF_TOOLS_PATH"

# --- Smoke test --------------------------------------------------------------
info "Verifying: sourcing export.sh and running idf.py --version"
if out="$(bash -c ". '$REPO_ROOT/scripts/idf-env.sh' >/dev/null && idf.py --version" 2>&1)"; then
  ok "$out"
else
  printf '%s\n' "$out" >&2
  die "ESP-IDF installed but export failed; see output above."
fi

cat <<EOF

ESP-IDF $ESP_IDF_REF is ready.
In each new shell where you build firmware:

    . $REPO_ROOT/scripts/idf-env.sh

then e.g.  cd firmware/bringup && idf.py set-target esp32s3 && idf.py build
EOF
