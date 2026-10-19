#!/usr/bin/env bash
# Install and start the host services as system services (rootful Podman Quadlet).
# Two modes: frigate (default: detection, recording, controller) and simple
# (motion JPEGs). The camera serves one stream client, so only one mode runs.
#
#   sudo host/scripts/install-services.sh [--mode frigate|simple] [--cameras a,b,c] [--no-start]
#   sudo host/scripts/install-services.sh --mode simple [--ignore-schedule] [--cameras a]
#
# --mode: frigate or simple. With no flag, use /etc/sentinel/mode if it exists,
# otherwise frigate. The chosen mode is written back to that file.
# --ignore-schedule: simple mode only. Record on motion at any time (daytime bench
# test). Not saved; the next run without the flag restores the schedule.
#
# Reads secrets/ (host/scripts/generate-secrets.sh). Safe to re-run: pulls and pins image
# digests, rewrites /etc/sentinel only where content changed, and restarts only the units
# whose inputs changed. Units are enabled at boot by their [Install] section.
# Quadlet units cannot be `systemctl disable`d. Removing the .container file and
# `systemctl daemon-reload` is how a mode's units are turned off. Volumes stay.
set -euo pipefail

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$script_dir/../.." && pwd)
secrets=$repo_root/secrets
# SENTINEL_ETC_DIR / SENTINEL_UNIT_DIR / SENTINEL_ALLOW_NONROOT exist for tests with stubbed tools.
etc=${SENTINEL_ETC_DIR:-/etc/sentinel}
units=${SENTINEL_UNIT_DIR:-/etc/containers/systemd}
CAMERAS=a,b,c
START=1
MODE=""
IGNORE_SCHEDULE=0

while [[ $# -gt 0 ]]; do
    case "$1" in
        --cameras) CAMERAS=${2:?}; shift ;;
        --no-start) START=0 ;;
        --mode) MODE=${2:?}; shift ;;
        --ignore-schedule) IGNORE_SCHEDULE=1 ;;
        -h|--help) awk 'NR == 1 { next } /^#/ { print; next } { exit }' "$0"; exit 0 ;;
        *) printf 'Unknown option: %s\n' "$1" >&2; exit 2 ;;
    esac
    shift
done

say() { printf '==> %s\n' "$*"; }
ok() { printf ' ok %s\n' "$*"; }
die() { printf 'ERR %s\n' "$*" >&2; exit 1; }

if [[ -z $MODE ]]; then
    if [[ -f $etc/mode ]]; then
        MODE=$(tr -d '[:space:]' < "$etc/mode")
    else
        MODE=frigate
    fi
fi
case $MODE in
    frigate|simple) ;;
    *) die "Unknown mode: $MODE (use frigate or simple)" ;;
esac
if [[ $IGNORE_SCHEDULE == 1 && $MODE != simple ]]; then
    die "--ignore-schedule applies only to simple mode"
fi

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

tmp_files=()
new_tmp() {
    local f
    f=$(mktemp)
    tmp_files+=("$f")
    printf '%s\n' "$f"
}
# Invoked from the EXIT trap below.
# shellcheck disable=SC2329
cleanup() {
    if ((${#tmp_files[@]} > 0)); then
        rm -f "${tmp_files[@]}"
    fi
    # secrets/ was written by root in a few places (digests, hashed passwords). Hand it back.
    if [[ -n ${SUDO_UID:-} ]]; then
        chown -R "$SUDO_UID:${SUDO_GID:-$SUDO_UID}" "$secrets" 2>/dev/null || true
    fi
}
trap cleanup EXIT

# Quadlet units cannot be `systemctl disable`d. Removing the .container file
# and the daemon-reload below is how a mode's units are turned off. Volumes and
# /etc/sentinel/frigate* stay, so switching back is one install command.
drop_container_unit() {
    local name=$1
    [[ -f ${units}/${name}.container ]] || return 0
    if systemctl is-active --quiet "${name}.service"; then
        systemctl stop "${name}.service"
    fi
    rm -f "${units}/${name}.container"
}

install_units() {
    local pair name src
    for pair in "$@"; do
        name=${pair%%:*}
        src=${pair#*:}
        if [[ ! -f ${units}/${name}.container ]] || unit_differs "$src" "${units}/${name}.container"; then
            install -m 0644 "$src" "${units}/${name}.container"
            case $name in
                mosquitto) restart_mosq=1 ;;
                frigate) restart_frigate=1 ;;
                sentinel-controller) restart_ctrl=1 ;;
                sentinel-recorder) restart_rec=1 ;;
            esac
        fi
    done
}

host_timezone() {
    local zone=""
    if command -v timedatectl >/dev/null 2>&1; then
        zone=$(timedatectl show -p Timezone --value 2>/dev/null || true)
    fi
    if [[ -z $zone || $zone == n/a ]]; then
        printf 'WARN timedatectl did not report a timezone; using UTC\n' >&2
        printf '%s' UTC
        return 0
    fi
    printf '%s' "$zone"
}

start_or_restart() {
    local unit=$1 flag=$2
    if systemctl is-active --quiet "$unit" && [[ $flag == 0 ]]; then
        ok "$unit already running, unchanged"
    elif systemctl is-active --quiet "$unit"; then
        systemctl restart "$unit" && ok "$unit restarted"
    else
        systemctl start "$unit" && ok "$unit started"
    fi
    return 0
}

verify_unit() {
    local u=$1 i
    for ((i = 1; i <= 30; i++)); do
        systemctl is-active --quiet "${u}.service" && break
        sleep 1
    done
    if systemctl is-active --quiet "${u}.service"; then
        ok "${u}.service active, boot: $(systemctl is-enabled "${u}.service" 2>&1 | tail -n 1)"
    else
        printf 'FAIL %s.service is %s. See: journalctl -u %s -e\n' \
            "$u" "$(systemctl is-active "${u}.service" || true)" "$u" >&2
        rc=1
    fi
}

# Quadlet's generated volume unit creates the volume. chown only the top
# directory: an earlier install left it root-owned, and a recursive chown
# would walk every frame. Sets VOLUME_MOUNT.
own_volume() {
    local unit=$1 volume=$2
    local mount
    systemctl start "$unit"
    mount=$(podman volume inspect "$volume" --format '{{.Mountpoint}}')
    chown 1000:1000 "$mount"
    VOLUME_MOUNT=$mount
    ok "$volume owned by uid 1000"
}

verify_recorder_access() {
    local sched_rc=0
    podman exec sentinel-recorder sentinel-recorder check-schedule >/dev/null || sched_rc=$?
    if [[ $sched_rc -eq 0 || $sched_rc -eq 1 ]]; then
        ok "recorder read /etc/sentinel/recorder.toml"
    else
        printf 'FAIL recorder cannot read /etc/sentinel/recorder.toml\n' >&2
        rc=1
    fi
    if podman exec sentinel-recorder sh -c 'test -w /var/lib/sentinel/recordings'; then
        ok "recordings volume writable by uid 1000"
    else
        printf 'FAIL volume not writable by uid 1000\n' >&2
        rc=1
    fi
}

verify_evidence_writable() {
    if podman exec sentinel-controller sh -c 'test -w /var/lib/sentinel/evidence'; then
        ok "evidence volume writable by uid 1000"
    else
        printf 'FAIL volume not writable by uid 1000\n' >&2
        rc=1
    fi
}

# latest.jpg newer than install_started means this run saw a frame. A miss is a
# note: the camera may simply be off. It does not fail the install.
note_fresh_frames() {
    local mount=$1
    local deadline name path mtime id
    local -a ids=() names=() still=()
    local IFS=,
    read -r -a ids <<< "${CAMERAS//[[:space:]]/}"
    for id in "${ids[@]}"; do
        [[ -n $id ]] || continue
        names+=("sentinel_${id}")
    done
    deadline=$((SECONDS + 20))
    while ((${#names[@]} > 0)); do
        if ((SECONDS > deadline)); then
            break
        fi
        still=()
        for name in "${names[@]}"; do
            path="${mount}/${name}/latest.jpg"
            if [[ -f $path ]] && mtime=$(stat -c %Y "$path") && ((mtime > install_started)); then
                ok "frame from ${name}"
            else
                still+=("$name")
            fi
        done
        if ((${#still[@]} == 0)); then
            return 0
        fi
        names=("${still[@]}")
        if ((SECONDS >= deadline)); then
            break
        fi
        sleep 1
    done
    for name in "${names[@]}"; do
        printf 'note: no frame from %s yet; is it powered and on the AP? journalctl -u sentinel-recorder -f\n' "$name"
    done
}

verify_mqtt() {
    local pw auth anon
    command -v mosquitto_sub >/dev/null || return 0
    pw=$(cat "$secrets/mosquitto/controller.password")
    # exit 27 = connected, then the -W timeout elapsed; 5 = refused
    set +e
    mosquitto_sub -h 127.0.0.1 -u controller -P "$pw" -t 'sentinel/+/state' -W 3 >/dev/null 2>&1
    auth=$?
    mosquitto_sub -h 127.0.0.1 -t 'sentinel/#' -W 3 >/dev/null 2>&1
    anon=$?
    set -e
    if [[ $auth -eq 27 ]]; then
        ok "MQTT: controller login accepted"
    else
        printf 'FAIL MQTT controller login (rc=%s)\n' "$auth" >&2
        rc=1
    fi
    if [[ $anon -ne 27 && $anon -ne 0 ]]; then
        ok "MQTT: anonymous refused"
    else
        printf 'FAIL MQTT accepts anonymous clients\n' >&2
        rc=1
    fi
}

restart_frigate=0
restart_mosq=0
restart_ctrl=0
restart_rec=0

say "Mode: $MODE"
if [[ $IGNORE_SCHEDULE == 1 ]]; then
    say "Schedule: ignored for this run (not saved)"
fi

# --- 1. Images ------------------------------------------------------------------
say "Pulling images and recording digests"
if [[ $MODE == simple ]]; then
    "$script_dir/pin-digests.sh" --skip-frigate
else
    "$script_dir/pin-digests.sh"
fi

# --- 2. Mosquitto ------------------------------------------------------------------
say "Mosquitto: password hashes, ACL, config"
# mosquitto_passwd salts every hash, so re-hashing always yields a different file. Only do it
# when the user list is newer, or the broker would restart on every re-run.
if [[ ! -f $secrets/mosquitto/passwords || $secrets/mosquitto/users -nt $secrets/mosquitto/passwords ]]; then
    "$script_dir/hash-mqtt-passwords.sh" >/dev/null
fi
install -d -m 0755 "$etc" "$etc/frigate" "$etc/mosquitto" "$units"
install_if_changed "$repo_root/host/mosquitto/mosquitto.conf" "$etc/mosquitto/mosquitto.conf" 0644
((CHANGED)) && restart_mosq=1
install_if_changed "$secrets/mosquitto/acl" "$etc/mosquitto/acl" 0644
((CHANGED)) && restart_mosq=1
install_if_changed "$secrets/mosquitto/passwords" "$etc/mosquitto/passwords" 0600
((CHANGED)) && restart_mosq=1
ok "$etc/mosquitto"

# --- 3. This mode's image and config (the other mode stays up if this fails) ---
if [[ $MODE == simple ]]; then
    say "Recorder: image, config, stream tokens"
    tz_name=$(host_timezone)
    rendered=$(new_tmp)
    rendered_env=$(new_tmp)
    ignore_args=()
    if [[ $IGNORE_SCHEDULE == 1 ]]; then
        ignore_args+=(--ignore-schedule)
    fi
    before=$(podman image inspect --format '{{.Id}}' localhost/sentinel-recorder:latest 2>/dev/null || true)
    podman build -q -t localhost/sentinel-recorder:latest \
        -f "$repo_root/host/recorder/Containerfile" "$repo_root/host/recorder" >/dev/null
    after=$(podman image inspect --format '{{.Id}}' localhost/sentinel-recorder:latest)
    [[ $before == "$after" ]] || restart_rec=1
    PYTHONPATH="$repo_root/host/provision" "$render_py" -W ignore -m sentinel_provision \
        --repo-root "$repo_root" render-recorder --cameras "$CAMERAS" --timezone "$tz_name" \
        --out "$rendered" --env-out "$rendered_env" "${ignore_args[@]}"
    # No secrets in this file. The container runs as uid 1000 and must read it.
    install_if_changed "$rendered" "$etc/recorder.toml" 0644
    ((CHANGED)) && restart_rec=1
    install_if_changed "$rendered_env" "$etc/recorder.env" 0600
    ((CHANGED)) && restart_rec=1
    ok "$etc/recorder.toml, $etc/recorder.env"
else
    say "Frigate: config with all cameras and stream tokens"
    rendered=$(new_tmp)
    PYTHONPATH="$repo_root/host/provision" "$render_py" -W ignore -m sentinel_provision \
        --repo-root "$repo_root" render-frigate --cameras "$CAMERAS" --out "$rendered"
    install_if_changed "$rendered" "$etc/frigate/config.yml" 0600
    ((CHANGED)) && restart_frigate=1
    install_if_changed "$secrets/frigate.env" "$etc/frigate.env" 0600
    ((CHANGED)) && restart_frigate=1
    ok "$etc/frigate/config.yml, $etc/frigate.env"

    say "Controller: image, config, MQTT password secret"
    install_if_changed "$repo_root/host/controller/config.toml" "$etc/controller.toml" 0644
    ((CHANGED)) && restart_ctrl=1
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
fi

# --- 4. Record the mode, then turn the other stack's units off -----------------
mode_tmp=$(new_tmp)
printf '%s\n' "$MODE" > "$mode_tmp"
install_if_changed "$mode_tmp" "$etc/mode" 0644
if [[ $MODE == simple ]]; then
    drop_container_unit frigate
    drop_container_unit sentinel-controller
else
    drop_container_unit sentinel-recorder
fi

# --- 5. Quadlet units ----------------------------------------------------------------------
say "Quadlet units"
for vol in mosquitto-data frigate-config frigate-media sentinel-evidence sentinel-recordings; do
    install_if_changed "$repo_root/host/quadlet/${vol}.volume" "${units}/${vol}.volume" 0644
done

if [[ $MODE == simple ]]; then
    install_units \
        "mosquitto:${repo_root}/host/quadlet/mosquitto.container" \
        "sentinel-recorder:${repo_root}/host/quadlet/sentinel-recorder.container"
    "$script_dir/pin-digests.sh" --no-pull --skip-frigate >/dev/null
else
    # Frigate gets only the /dev/dri nodes this machine has (probe-host.sh lists them).
    tmp_unit=$(new_tmp)
    while IFS= read -r line; do
        if [[ $line =~ ^AddDevice=(/dev/dri/[^[:space:]]+)$ && ! -e ${BASH_REMATCH[1]} ]]; then
            printf 'note: %s absent, dropped from frigate.container\n' "${BASH_REMATCH[1]}" >&2
            continue
        fi
        printf '%s\n' "$line"
    done <"$repo_root/host/quadlet/frigate.container" >"$tmp_unit"
    grep -q '^AddDevice=' "$tmp_unit" || printf 'WARN no /dev/dri nodes: OpenVINO GPU detection will fail (see RUNBOOK step 1)\n' >&2
    install_units \
        "mosquitto:${repo_root}/host/quadlet/mosquitto.container" \
        "frigate:${tmp_unit}" \
        "sentinel-controller:${repo_root}/host/quadlet/sentinel-controller.container"
    "$script_dir/pin-digests.sh" --no-pull >/dev/null
fi
systemctl daemon-reload
ok "$units"

# --- 6. Volume ownership (before the recorder or controller starts) ------------
recordings_mount=
if [[ $MODE == simple ]]; then
    own_volume sentinel-recordings-volume.service sentinel-recordings
    recordings_mount=$VOLUME_MOUNT
else
    own_volume sentinel-evidence-volume.service sentinel-evidence
fi

# --- 7. Start --------------------------------------------------------------------------------
if [[ $MODE == simple ]]; then
    start_names=(mosquitto sentinel-recorder)
else
    start_names=(mosquitto frigate sentinel-controller)
fi
if [[ $START == 0 ]]; then
    say "Not starting (--no-start). Start with: systemctl start ${start_names[*]}"
    exit 0
fi
say "Starting services"
install_started=$(date +%s)
for name in "${start_names[@]}"; do
    needs=0
    case $name in
        mosquitto) needs=$restart_mosq ;;
        frigate) needs=$restart_frigate ;;
        sentinel-controller) needs=$restart_ctrl ;;
        sentinel-recorder) needs=$restart_rec ;;
    esac
    start_or_restart "${name}.service" "$needs"
done

# --- 8. Verify -----------------------------------------------------------------------------------
say "Verifying"
rc=0
for name in "${start_names[@]}"; do
    verify_unit "$name"
done
verify_mqtt

if [[ $MODE == simple ]]; then
    verify_recorder_access
    note_fresh_frames "$recordings_mount"
fi

if [[ $MODE == frigate ]]; then
    verify_evidence_writable
    printf 'Waiting for Frigate API (first start downloads face models)...\n'
    for ((i = 1; i <= 90; i++)); do
        curl -fsS -m 2 http://127.0.0.1:5000/api/version >/dev/null 2>&1 && {
            ok "Frigate API up: $(curl -fsS http://127.0.0.1:5000/api/version)"
            break
        }
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
fi
exit "$rc"
