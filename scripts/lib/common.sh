# shellcheck shell=bash
# shellcheck disable=SC2034  # consumed by the scripts that source this file
# Shared helpers for the install scripts. Source, don't execute.

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=versions.sh
. "$REPO_ROOT/scripts/lib/versions.sh"

SENTINEL_DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/jack-sentinel"
SENTINEL_CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/jack-sentinel"
SENTINEL_ENV_FILE="$SENTINEL_CONFIG_DIR/env.sh"
SECRETS_DIR="$REPO_ROOT/secrets"

if [[ -t 1 ]]; then
  _c_info=$'\e[1;34m' _c_ok=$'\e[1;32m' _c_warn=$'\e[1;33m' _c_err=$'\e[1;31m' _c_off=$'\e[0m'
else
  _c_info='' _c_ok='' _c_warn='' _c_err='' _c_off=''
fi

info() { printf '%s==>%s %s\n' "$_c_info" "$_c_off" "$*"; }
ok()   { printf '%s ok%s %s\n' "$_c_ok" "$_c_off" "$*"; }
warn() { printf '%s !!%s %s\n' "$_c_warn" "$_c_off" "$*" >&2; }
die()  { printf '%sERR%s %s\n' "$_c_err" "$_c_off" "$*" >&2; exit 1; }

require_not_root() {
  [[ $EUID -ne 0 ]] || die "Run as your normal user; the script calls sudo where it needs to."
}

have() { command -v "$1" >/dev/null 2>&1; }

# confirm "question" -> 0 for yes. Honors ASSUME_YES=1. Defaults to yes on empty input.
confirm() {
  [[ "${ASSUME_YES:-0}" == 1 ]] && return 0
  [[ -t 0 ]] || return 1
  local reply
  read -r -p "$1 [Y/n] " reply
  [[ -z "$reply" || "$reply" =~ ^[Yy] ]]
}

# Set KEY=VALUE in the per-user env file that scripts/idf-env.sh and the host tools read.
env_set() {
  local key="$1" value="$2"
  mkdir -p "$SENTINEL_CONFIG_DIR"
  touch "$SENTINEL_ENV_FILE"
  local tmp
  tmp="$(mktemp)"
  grep -v "^export ${key}=" "$SENTINEL_ENV_FILE" > "$tmp" || true
  printf 'export %s=%q\n' "$key" "$value" >> "$tmp"
  mv "$tmp" "$SENTINEL_ENV_FILE"
}

# Print the real interpreter path of a Python in [3.min, 3.max], or return 1.
# Resolves pyenv shims to the concrete executable so venvs and ESP-IDF stay stable
# when the pyenv global changes later.
python_ok() {
  local py="$1" min="${2:-$PY_MIN_MINOR}" max="${3:-$PY_MAX_MINOR}"
  have "$py" || [[ -x "$py" ]] || return 1
  "$py" - "$min" "$max" <<'EOF' 2>/dev/null
import sys
lo, hi = int(sys.argv[1]), int(sys.argv[2])
v = sys.version_info
if v.major == 3 and lo <= v.minor <= hi:
    import ssl, venv  # noqa: F401  (ESP-IDF and pip both need these)
    print(sys.executable)
else:
    sys.exit(1)
EOF
}

# pick_python [min] [max]: honors $SENTINEL_PYTHON, then the system Python, then python3 on PATH.
pick_python() {
  local cand exe
  for cand in "${SENTINEL_PYTHON:-}" /usr/bin/python3 python3; do
    [[ -n "$cand" ]] || continue
    if exe="$(python_ok "$cand" "$@")"; then
      printf '%s\n' "$exe"
      return 0
    fi
  done
  return 1
}

os_id() { . /etc/os-release && printf '%s\n' "${ID:-unknown}"; }

user_in_group() { id -nG "$USER" | tr ' ' '\n' | grep -qx "$1"; }

# provision_cli <args>: run sentinel-provision from the repo venv, or from the source tree with
# a system Python (it has no third-party dependencies), so secrets work before the venv exists.
provision_cli() {
  local py="$REPO_ROOT/.venv/bin/python"
  [[ -x "$py" ]] || py="$(pick_python "$PY_MIN_MINOR" "$PY_MAX_MINOR")" \
    || die "Need Python 3.$PY_MIN_MINOR+ to run sentinel-provision (set SENTINEL_PYTHON)."
  PYTHONPATH="$REPO_ROOT/host/provision${PYTHONPATH:+:$PYTHONPATH}" \
    "$py" -W ignore -m sentinel_provision --repo-root "$REPO_ROOT" "$@"
}

# kv_get FILE KEY: value of KEY=VALUE from a bash-style env file, without executing the file.
# Strips one layer of surrounding quotes; empty if unset.
kv_get() {
  [[ -f "$1" ]] || return 0
  local v
  v="$(sed -n "s/^[[:space:]]*\(export[[:space:]]\+\)\?$2=//p" "$1" | tail -n1)"
  v="${v%\'}"; v="${v#\'}"; v="${v%\"}"; v="${v#\"}"
  printf '%s' "$v"
}

# ap_env_get KEY: value from secrets/ap.env. Never echo the PSK to a terminal.
ap_env_get() { kv_get "$SECRETS_DIR/ap.env" "$1"; }
