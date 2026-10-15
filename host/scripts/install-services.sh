#!/usr/bin/env bash
# Install and start the host services as system services (rootful Podman Quadlet):
# mosquitto, Frigate and sentinel-controller. RUNBOOK steps 4-5 plus the controller, in one go.
#
#   sudo host/scripts/install-services.sh [--cameras a,b,c] [--no-start]
#
# Reads secrets/ (host/scripts/generate-secrets.sh). Safe to re-run: pulls and pins image
# digests, rewrites /etc/sentinel only where content changed, and restarts only the units
# whose inputs changed. Units are enabled at boot by their [Install] section.
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$script_dir/../.." && pwd)
secrets=$repo_root/secrets
# SENTINEL_ETC_DIR / SENTINEL_UNIT_DIR / SENTINEL_ALLOW_NONROOT exist for tests with stubbed tools.
etc=${SENTINEL_ETC_DIR:-/etc/sentinel}
units=${SENTINEL_UNIT_DIR:-/etc/containers/systemd}
CAMERAS=a,b,c START=1

while [[ $# -gt 0 ]]; do
    case "$1" in
        --cameras) CAMERAS=${2:?}; shift ;;
        --no-start) START=0 ;;
        -h|--help) sed -n '2,10p' "$0"; exit 0 ;;
        *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
    esac
    shift
done

say() { printf '==> %s\n' "$*"; }
ok() { printf ' ok %s\n' "$*"; }
die() { printf 'ERR %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 || ${SENTINEL_ALLOW_NONROOT:-0} == 1 ]] || die "Run as root: sudo $0"
command -v podman >/dev/null || die "podman is not installed (scripts/install-fedora.sh installs it)"
for f in secrets/mosquitto/users secrets/mosquitto/acl secrets/mosquitto/controller.password secrets/frigate.env; do
    [[ -f $repo_root/$f ]] || die "Missing $f. Run host/scripts/generate-secrets.sh first."
done

# Run the unprivileged python of whoever invoked sudo for config rendering; it needs only the stdlib.
render_py=${SENTINEL_RENDER_PYTHON:-$(command -v python3)}

# install_if_changed SRC DEST MODE -> sets CHANGED=1 when DEST differs
CHANGED=0
install_if_changed() {
    local src=$1 dest=$2 mode=$3
    if [[ -f $dest ]] && cmp -s "$src" "$dest" && [[ "$(stat -c %a "$dest")" == "${mode#0}" ]]; then
        CHANGED=0
        return 0
    fi
    install -D -m "$mode" "$src" "$dest"
    CHANGED=1
}

# Unit comparison ignores Image= (pin-digests.sh rewrites it to name:tag@sha256:...).
unit_differs() { ! diff -q <(grep -v '^Image=' "$1") <(grep -v '^Image=' "$2" 2>/dev/null) >/dev/null 2>&1; }

restart_frigate=0 restart_mosq=0 restart_ctrl=0

# --- 1. Images ------------------------------------------------------------------
say "Pulling images and recording digests"
"$script_dir/pin-digests.sh"

# --- 2. Mosquitto ------------------------------------------------------------------
say "Mosquitto: password hashes, ACL, config"
# mosquitto_passwd salts every hash, so re-hashing always yields a different file. Only do it
# when the user list is newer, or the broker would restart on every re-run.
if [[ ! -f $secrets/mosquitto/passwords || $secrets/mosquitto/users -nt $secrets/mosquitto/passwords ]]; then
    "$script_dir/hash-mqtt-passwords.sh" >/dev/null
fi
install -d -m 0755 "$etc" "$etc/frigate" "$etc/mosquitto" "$units"
install_if_changed "$repo_root/host/mosquitto/mosquitto.conf" "$etc/mosquitto/mosquitto.conf" 0644; ((CHANGED)) && restart_mosq=1
install_if_changed "$secrets/mosquitto/acl" "$etc/mosquitto/acl" 0644; ((CHANGED)) && restart_mosq=1
install_if_changed "$secrets/mosquitto/passwords" "$etc/mosquitto/passwords" 0600; ((CHANGED)) && restart_mosq=1
ok "$etc/mosquitto"

# --- 3. Frigate -----------------------------------------------------------------------
say "Frigate: config with all cameras and stream tokens"
rendered=$(mktemp)
cleanup() {
    rm -f "$rendered" "${tmp_unit:-}"
    # secrets/ was written by root in a few places (digests, hashed passwords). Hand it back.
    if [[ -n ${SUDO_UID:-} ]]; then chown -R "$SUDO_UID:${SUDO_GID:-$SUDO_UID}" "$secrets" 2>/dev/null || true; fi
}
trap cleanup EXIT
PYTHONPATH=$repo_root/host/provision "$render_py" -W ignore -m sentinel_provision \
    --repo-root "$repo_root" render-frigate --cameras "$CAMERAS" --out "$rendered"
install_if_changed "$rendered" "$etc/frigate/config.yml" 0600; ((CHANGED)) && restart_frigate=1
install_if_changed "$secrets/frigate.env" "$etc/frigate.env" 0600; ((CHANGED)) && restart_frigate=1
ok "$etc/frigate/config.yml, $etc/frigate.env"

# --- 4. Controller -----------------------------------------------------------------------
say "Controller: image, config, MQTT password secret"
install_if_changed "$repo_root/host/controller/config.toml" "$etc/controller.toml" 0644; ((CHANGED)) && restart_ctrl=1
before=$(podman image inspect --format '{{.Id}}' localhost/sentinel-controller:latest 2>/dev/null || true)
podman build -q -t localhost/sentinel-controller:latest \
    -f "$repo_root/host/controller/Containerfile" "$repo_root/host/controller" >/dev/null
after=$(podman image inspect --format '{{.Id}}' localhost/sentinel-controller:latest)
[[ $before == "$after" ]] || restart_ctrl=1
want=$(cat "$secrets/mosquitto/controller.password")
have=$(podman secret inspect --showsecret --format '{{.SecretData}}' sentinel-controller-mqtt-password 2>/dev/null || true)
if [[ $have != "$want" ]]; then
    podman secret rm sentinel-controller-mqtt-password >/dev/null 2>&1 || true
    printf '%s' "$want" | podman secret create sentinel-controller-mqtt-password - >/dev/null
    restart_ctrl=1
fi
ok "localhost/sentinel-controller:latest, podman secret sentinel-controller-mqtt-password"

# --- 5. Quadlet units ----------------------------------------------------------------------
say "Quadlet units"
for vol in mosquitto-data frigate-config frigate-media sentinel-evidence; do
    install_if_changed "$repo_root/host/quadlet/$vol.volume" "$units/$vol.volume" 0644
done

# Frigate gets only the /dev/dri nodes this machine has (probe-host.sh lists them).
tmp_unit=$(mktemp)
while IFS= read -r line; do
    if [[ $line =~ ^AddDevice=(/dev/dri/[^[:space:]]+)$ && ! -e ${BASH_REMATCH[1]} ]]; then
        printf 'note: %s absent, dropped from frigate.container\n' "${BASH_REMATCH[1]}" >&2
        continue
    fi
    printf '%s\n' "$line"
done <"$repo_root/host/quadlet/frigate.container" >"$tmp_unit"
grep -q '^AddDevice=' "$tmp_unit" || printf 'WARN no /dev/dri nodes: OpenVINO GPU detection will fail (see RUNBOOK step 1)\n' >&2

for pair in "mosquitto:$repo_root/host/quadlet/mosquitto.container" \
            "frigate:$tmp_unit" \
            "sentinel-controller:$repo_root/host/quadlet/sentinel-controller.container"; do
    name=${pair%%:*} src=${pair#*:}
    if [[ ! -f $units/$name.container ]] || unit_differs "$src" "$units/$name.container"; then
        install -m 0644 "$src" "$units/$name.container"
        case $name in
            mosquitto) restart_mosq=1 ;;
            frigate) restart_frigate=1 ;;
            *) restart_ctrl=1 ;;
        esac
    fi
done
"$script_dir/pin-digests.sh" --no-pull >/dev/null   # re-pin Image= in the units just installed
systemctl daemon-reload
ok "$units"

# --- 6. Start --------------------------------------------------------------------------------
if [[ $START == 0 ]]; then
    say "Not starting (--no-start). Start with: systemctl start mosquitto frigate sentinel-controller"
    exit 0
fi
say "Starting services"
start_or_restart() {   # start_or_restart UNIT NEEDS_RESTART
    if systemctl is-active --quiet "$1" && [[ $2 == 0 ]]; then
        ok "$1 already running, unchanged"
    elif systemctl is-active --quiet "$1"; then
        systemctl restart "$1" && ok "$1 restarted"
    else
        systemctl start "$1" && ok "$1 started"
    fi
}
start_or_restart mosquitto.service "$restart_mosq"
start_or_restart frigate.service "$restart_frigate"
start_or_restart sentinel-controller.service "$restart_ctrl"

# --- 7. Verify -----------------------------------------------------------------------------------
say "Verifying"
rc=0
for u in mosquitto frigate sentinel-controller; do
    for _ in $(seq 1 30); do systemctl is-active --quiet "$u.service" && break; sleep 1; done
    if systemctl is-active --quiet "$u.service"; then
        ok "$u.service active, boot: $(systemctl is-enabled "$u.service" 2>&1 | tail -n1)"
    else
        printf 'FAIL %s.service is %s. See: journalctl -u %s -e\n' "$u" "$(systemctl is-active "$u.service" || true)" "$u" >&2
        rc=1
    fi
done

if command -v mosquitto_sub >/dev/null; then
    pw=$(cat "$secrets/mosquitto/controller.password")
    # exit 27 = connected, then the -W timeout elapsed; 5 = refused
    set +e
    mosquitto_sub -h 127.0.0.1 -u controller -P "$pw" -t 'sentinel/+/state' -W 3 >/dev/null 2>&1; auth=$?
    mosquitto_sub -h 127.0.0.1 -t 'sentinel/#' -W 3 >/dev/null 2>&1; anon=$?
    set -e
    [[ $auth -eq 27 ]] && ok "MQTT: controller login accepted" || { printf 'FAIL MQTT controller login (rc=%s)\n' "$auth" >&2; rc=1; }
    [[ $anon -ne 27 && $anon -ne 0 ]] && ok "MQTT: anonymous refused" || { printf 'FAIL MQTT accepts anonymous clients\n' >&2; rc=1; }
fi

printf 'Waiting for Frigate API (first start downloads face models)...\n'
for _ in $(seq 1 90); do
    curl -fsS -m 2 http://127.0.0.1:5000/api/version >/dev/null 2>&1 && { ok "Frigate API up: $(curl -fsS http://127.0.0.1:5000/api/version)"; break; }
    sleep 2
done

# Frigate prints the generated admin password once at first start.
if [[ ! -f $secrets/frigate-admin.txt ]]; then
    line=$(journalctl -u frigate.service --no-pager 2>/dev/null | grep -i 'password' | head -n 3 || true)
    if [[ -n $line ]]; then
        (umask 077; printf '%s\n' "$line" >"$secrets/frigate-admin.txt")
        ok "Frigate admin login lines saved to secrets/frigate-admin.txt (best effort; change it under Settings > Users)"
    else
        printf 'note: no admin password line in the Frigate journal yet; look with: journalctl -u frigate | grep -i password\n'
    fi
fi
exit $rc
