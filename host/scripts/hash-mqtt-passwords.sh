#!/usr/bin/env bash
# Hash secrets/mosquitto/users with the mosquitto image's mosquitto_passwd.
# Run as root so the hash matches the image store used by the system Quadlet.
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$script_dir/../.." && pwd)
users=$repo_root/secrets/mosquitto/users
out_dir=$repo_root/secrets/mosquitto
image=${MOSQUITTO_IMAGE:-docker.io/library/eclipse-mosquitto:2}

if [[ "$(id -u)" -ne 0 && "${SENTINEL_ALLOW_NONROOT:-0}" != 1 ]]; then
    printf 'Run as root so podman uses the system image store: sudo %s\n' "$0" >&2
    exit 1
fi

[[ -f "$users" ]] || {
    printf 'Missing %s. Run host/scripts/generate-secrets.sh first.\n' "$users" >&2
    exit 1
}

command -v podman >/dev/null 2>&1 || {
    printf 'podman is not installed\n' >&2
    exit 1
}

podman image inspect "$image" >/dev/null 2>&1 || {
    printf 'Image %s is not present. Run host/scripts/pin-digests.sh first.\n' "$image" >&2
    exit 1
}

rm -f "$out_dir/passwords"
podman run --rm \
    --entrypoint /bin/sh \
    -v "$users:/work/users:ro,Z" \
    -v "$out_dir:/work/out:Z" \
    "$image" \
    -c 'set -eu
umask 077
out=/work/out/passwords
rm -f "$out"
first=1
while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
        ""|"#"*) continue ;;
    esac
    user=${line%%:*}
    pass=${line#*:}
    if [ "$user" = "$line" ] || [ -z "$user" ] || [ -z "$pass" ]; then
        echo "bad users line" >&2
        exit 1
    fi
    if [ "$first" -eq 1 ]; then
        mosquitto_passwd -b -c "$out" "$user" "$pass"
        first=0
    else
        mosquitto_passwd -b "$out" "$user" "$pass"
    fi
done < /work/users'

chmod 600 "$out_dir/passwords"
printf 'Wrote %s\n' "$out_dir/passwords"
