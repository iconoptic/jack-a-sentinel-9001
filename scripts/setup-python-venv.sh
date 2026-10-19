#!/usr/bin/env bash
# Create/refresh the repo-local Python venv (.venv) for host-side tools and tests:
#   - esp_prov runtime deps (BLE provisioning): bleak, cryptography, protobuf
#   - host/controller  (editable, with [dev] extras) once its package is installable
#   - host/provision   (editable, with [dev] extras) once it exists (Phase 4)
#   - host/recorder    (editable, with [dev] extras) once its package is installable
#
# Safe to re-run; it only adds/upgrades. ESP-IDF keeps its own separate venv.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
require_not_root

VENV="$REPO_ROOT/.venv"
PY="$(pick_python "$PY_MIN_MINOR" "$PY_MAX_MINOR")" \
  || die "Need Python 3.$PY_MIN_MINOR–3.$PY_MAX_MINOR with ssl+venv. Set SENTINEL_PYTHON=/path/to/python3.x"

if [[ -x "$VENV/bin/python" ]] && ! python_ok "$VENV/bin/python" >/dev/null; then
  warn "Existing .venv uses an unsupported Python; recreating it."
  rm -rf "$VENV"
fi
if [[ ! -x "$VENV/bin/python" ]]; then
  info "Creating .venv with $PY ($("$PY" --version 2>&1))"
  "$PY" -m venv "$VENV"
fi
VPY="$VENV/bin/python"
"$VPY" -m pip install --quiet --upgrade pip

info "Installing esp_prov runtime deps"
"$VPY" -m pip install --quiet --upgrade 'bleak>=0.22' 'cryptography>=42' 'protobuf>=4.21,<8'
ok "bleak, cryptography, protobuf"

# install_local <dir>: editable install with [dev] extras; non-fatal while a phase is in progress.
install_local() {
  local dir="$REPO_ROOT/$1"
  if [[ -f "$dir/pyproject.toml" ]]; then
    if "$VPY" -m pip install --quiet -e "${dir}[dev]"; then
      ok "$1 (editable, dev extras)"
    else
      warn "$1 is not installable yet (incomplete package?). Re-run this script once it builds."
    fi
  elif [[ -f "$dir/requirements.txt" ]]; then
    "$VPY" -m pip install --quiet -r "$dir/requirements.txt" && ok "$1 requirements.txt"
  else
    info "$1: no package yet, skipped"
  fi
}
install_local host/controller
install_local host/provision
install_local host/recorder

cat <<EOF

Venv ready: $VENV
    . .venv/bin/activate        # or call .venv/bin/python / .venv/bin/pytest directly
EOF
