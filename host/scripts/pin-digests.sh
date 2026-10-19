#!/usr/bin/env bash
# Pull Frigate and Mosquitto as root, record digests under secrets/digests.txt,
# and pin Image= in the installed Quadlet units when those files exist.
# Does not edit the git checkout. Digests are recorded on Fedora, not here.
#   sudo host/scripts/pin-digests.sh                         # pull, record, pin both
#   sudo host/scripts/pin-digests.sh --no-pull               # pin from images already in the store
#   sudo host/scripts/pin-digests.sh --skip-frigate          # simple mode: Mosquitto only
#   sudo host/scripts/pin-digests.sh --no-pull --skip-frigate
# Default (no --skip-frigate) still pulls and pins Frigate and Mosquitto.
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$script_dir/../.." && pwd)
frigate_ref=ghcr.io/blakeblackshear/frigate:0.18.1
mosquitto_ref=docker.io/library/eclipse-mosquitto:2
dest=$repo_root/secrets/digests.txt
unit_dir=${SENTINEL_UNIT_DIR:-/etc/containers/systemd}
PULL=1
SKIP_FRIGATE=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-pull) PULL=0 ;;
        --skip-frigate) SKIP_FRIGATE=1 ;;
        -h|--help) awk 'NR == 1 { next } /^#/ { print; next } { exit }' "$0"; exit 0 ;;
        *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
    esac
    shift
done

if [[ "$(id -u)" -ne 0 && "${SENTINEL_ALLOW_NONROOT:-0}" != 1 ]]; then
    printf 'Run as root: sudo %s\n' "$0" >&2
    exit 1
fi

command -v podman >/dev/null 2>&1 || {
    printf 'podman is not installed\n' >&2
    exit 1
}

if [[ $PULL == 1 ]]; then
    if [[ $SKIP_FRIGATE == 0 ]]; then
        podman pull "$frigate_ref"
    fi
    podman pull "$mosquitto_ref"
fi

pin_of() {
    local ref=$1 prefix line hex
    prefix=${ref%:*}
    line=$(podman image inspect --format '{{range .RepoDigests}}{{.}}{{"\n"}}{{end}}' "$ref" \
        | awk -v p="$prefix@" 'index($0, p) == 1 { print; exit }')
    [[ -n "$line" ]] || {
        printf 'No RepoDigest for %s\n' "$ref" >&2
        exit 1
    }
    hex=${line#*@}
    printf '%s@%s\n' "$ref" "$hex"
}

mosquitto_pin=$(pin_of "$mosquitto_ref")
frigate_pin=""
if [[ $SKIP_FRIGATE == 0 ]]; then
    frigate_pin=$(pin_of "$frigate_ref")
elif [[ -f $dest ]]; then
    # Keep a Frigate pin recorded earlier so a later frigate-mode run still has it
    # until that run pulls again. Avoid a pipe here: pipefail plus head's SIGPIPE
    # would fail the script.
    frigate_pin=$(sed -n 's/^frigate=//p' "$dest")
    frigate_pin=${frigate_pin%%$'\n'*}
fi

umask 077
mkdir -p "$repo_root/secrets"
{
    printf 'pulled_at=%s\n' "$(date -Is)"
    if [[ -n $frigate_pin ]]; then
        printf 'frigate=%s\n' "$frigate_pin"
    fi
    printf 'mosquitto=%s\n' "$mosquitto_pin"
} >"$dest"
printf 'Wrote %s\n' "$dest"

rewrite_unit() {
    local unit=$1 ref=$2 pinned=$3 tmp
    [[ -f "$unit" ]] || {
        printf 'No installed unit %s yet. Re-run this script after copying Quadlet files.\n' "$unit"
        return 0
    }
    tmp=$(mktemp)
    awk -v ref="$ref" -v pinned="$pinned" '
        $0 == "Image=" ref { print "Image=" pinned; next }
        index($0, "Image=" ref "@sha256:") == 1 { print "Image=" pinned; next }
        { print }
    ' "$unit" >"$tmp"
    if ! grep -q "^Image=${pinned}$" "$tmp"; then
        printf 'Did not find an Image= line for %s in %s\n' "$ref" "$unit" >&2
        rm -f "$tmp"
        exit 1
    fi
    install -m 0644 "$tmp" "$unit"
    rm -f "$tmp"
    printf 'Pinned %s\n' "$unit"
}

if [[ $SKIP_FRIGATE == 0 ]]; then
    rewrite_unit "$unit_dir/frigate.container" "$frigate_ref" "$frigate_pin"
fi
rewrite_unit "$unit_dir/mosquitto.container" "$mosquitto_ref" "$mosquitto_pin"

if [[ -f "$unit_dir/frigate.container" || -f "$unit_dir/mosquitto.container" ]]; then
    systemctl daemon-reload
    printf 'systemctl daemon-reload done\n'
fi
