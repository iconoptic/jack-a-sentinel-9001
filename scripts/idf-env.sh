# shellcheck shell=bash
# shellcheck disable=SC1090,SC1091,SC2317  # sourced into an interactive shell; paths are per-user
# Source this (don't execute) to get idf.py, esptool, etc. in the current shell:
#
#     . scripts/idf-env.sh
#
# Reads the paths that scripts/install-esp-idf.sh recorded, pins the same Python that
# ESP-IDF was installed with, then sources ESP-IDF's export.sh.

_sentinel_env="${XDG_CONFIG_HOME:-$HOME/.config}/jack-sentinel/env.sh"
if [ ! -f "$_sentinel_env" ]; then
  echo "jack-sentinel: $_sentinel_env not found. Run scripts/install-esp-idf.sh first." >&2
  return 1 2>/dev/null || exit 1
fi
. "$_sentinel_env"
unset _sentinel_env

if [ -z "${SENTINEL_IDF_PATH:-}" ] || [ ! -f "$SENTINEL_IDF_PATH/export.sh" ]; then
  echo "jack-sentinel: ESP-IDF not recorded or missing. Run scripts/install-esp-idf.sh." >&2
  return 1 2>/dev/null || exit 1
fi

case ":$PATH:" in
  *":$SENTINEL_IDF_PYTHON_SHIM:"*) ;;
  *) PATH="$SENTINEL_IDF_PYTHON_SHIM:$PATH"; export PATH ;;
esac

. "$SENTINEL_IDF_PATH/export.sh"
