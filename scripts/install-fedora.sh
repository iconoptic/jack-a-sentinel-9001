#!/usr/bin/env bash
# Fedora host (cubicle box): one command from a fresh checkout to a running system.
#
#   scripts/install-fedora.sh                 # packages, secrets, hidden AP, services, checks
#   scripts/install-fedora.sh --with-esp-idf  # also full ESP-IDF, to flash cameras from this box
#   scripts/install-fedora.sh -y              # don't prompt
#
# What "installed" means after this script:
#   - secrets/ generated once and kept (random hidden SSID, WPA2 passphrase, MQTT passwords,
#     per-camera stream tokens). Nothing is printed; nothing is committed.
#   - the hidden camera AP exists as the NetworkManager profile `sentinel-ap` (autoconnect, so
#     it returns after every reboot) with firewalld zone `sentinel`
#   - mosquitto, Frigate and sentinel-controller run as system services (rootful Quadlet,
#     images pinned by digest) and start at boot
#   - esp_prov and the repo .venv for the BLE fallback path
# Then flash the cameras: scripts/install-esp32.sh all  (on this box or on the Arch machine).
#
# Fine-grained control (all default to on):
#   --no-deploy         packages and checks only (the old behaviour)
#   --no-ap             skip the AP stage      --no-services   skip the container services
#   --wifi-iface IF     AP interface (default: first AP-capable Wi-Fi device)
#   --channel N         1, 6 or 11 (default: scan and pick the quietest)
#   --cameras a,b,c     cameras to provision (default: all three)
#   --pull-images       accepted for compatibility; services always pull and pin digests
#   --no-esp-prov       skip esp_prov
#
# Idempotent: re-running changes only what is missing or different.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"
require_not_root

WITH_IDF=0 WITH_PROV=1 DEPLOY=1 DO_AP=1 DO_SERVICES=1 IFACE="" CHANNEL="" CAMERAS="a,b,c"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --pull-images)  ;;
    --with-esp-idf) WITH_IDF=1 ;;
    --no-esp-prov)  WITH_PROV=0 ;;
    --no-deploy)    DEPLOY=0 ;;
    --no-ap)        DO_AP=0 ;;
    --no-services)  DO_SERVICES=0 ;;
    --wifi-iface)   IFACE="${2:?}"; shift ;;
    --channel)      CHANNEL="${2:?}"; shift ;;
    --cameras)      CAMERAS="${2:?}"; shift ;;
    -y|--yes)       export ASSUME_YES=1 ;;
    -h|--help)      sed -n '2,27p' "$0"; exit 0 ;;
    *)              die "Unknown option: $1 (see --help)" ;;
  esac
  shift
done

. /etc/os-release
[[ "${ID:-}" == fedora ]] || die "This is for Fedora (found ID=${ID:-?})."
[[ ! -e /run/ostree-booted ]] || die "Atomic Fedora (rpm-ostree) detected; layer these packages with rpm-ostree instead."
info "Fedora ${VERSION_ID:-?} ($(uname -r))"

PACKAGES=(
  # Containers: Quadlet ships with podman (>= 4.4)
  podman
  # Camera AP: hidden-SSID AP mode on the built-in Intel Wi-Fi
  NetworkManager NetworkManager-wifi wpa_supplicant iw
  firewalld
  # Provisioning over BLE (bleak talks to BlueZ over D-Bus); rfkill
  bluez util-linux
  # Python for sentinel-controller / sentinel-provision / esp_prov
  python3 python3-pip
  # Diagnostics: probe-host.sh, MQTT + stream checks, iGPU/VAAPI
  git curl jq pciutils usbutils mosquitto ffmpeg-free libva-utils igt-gpu-tools ShellCheck
  # Clock source for evidence manifests (CONTRACTS.md)
  chrony
)
# Nice to have; skipped if the repo doesn't carry them (e.g. without RPM Fusion).
OPTIONAL_PACKAGES=(libva-intel-media-driver lm_sensors)
IDF_PACKAGES=(gcc make git wget2-wget flex bison gperf python3 python3-pip cmake ninja-build ccache dfu-util libusb1 libffi-devel openssl-devel)

# --- Packages ----------------------------------------------------------------
want=("${PACKAGES[@]}")
[[ $WITH_IDF == 1 ]] && want+=("${IDF_PACKAGES[@]}")
missing=()
for p in "${want[@]}"; do rpm -q "$p" >/dev/null 2>&1 || missing+=("$p"); done
if ((${#missing[@]})); then
  info "Installing: ${missing[*]}"
  sudo dnf install -y "${missing[@]}"
else
  ok "All required packages already installed"
fi

opt_missing=()
for p in "${OPTIONAL_PACKAGES[@]}"; do rpm -q "$p" >/dev/null 2>&1 || opt_missing+=("$p"); done
if ((${#opt_missing[@]})); then
  info "Optional: ${opt_missing[*]}"
  if dnf --version 2>/dev/null | grep -qi dnf5; then
    sudo dnf install -y --skip-unavailable "${opt_missing[@]}" || warn "Optional packages skipped"
  else
    sudo dnf install -y --setopt=strict=0 "${opt_missing[@]}" || warn "Optional packages skipped"
  fi
fi

# --- Services ----------------------------------------------------------------
systemctl is-active --quiet NetworkManager || die "NetworkManager is not running; the camera AP depends on it."
ok "NetworkManager active"

if ! systemctl is-enabled --quiet bluetooth || ! systemctl is-active --quiet bluetooth; then
  info "Enabling bluetooth.service"
  sudo systemctl enable --now bluetooth
fi
sudo rfkill unblock bluetooth || true
ok "bluetooth active"

if systemctl is-enabled --quiet chronyd 2>/dev/null; then
  systemctl is-active --quiet chronyd || sudo systemctl start chronyd
else
  sudo systemctl enable --now chronyd || warn "chronyd not enabled; evidence timestamps rely on the system clock"
fi

if systemctl is-active --quiet firewalld; then
  ok "firewalld active (zone: $(firewall-cmd --get-default-zone 2>/dev/null || echo ?))"
elif [[ $DEPLOY == 1 && $DO_AP == 1 ]] || confirm "firewalld is not running. Enable it now?"; then
  # The AP's `sentinel` zone (DROP, TCP 1883 only) is what keeps the camera network contained.
  sudo systemctl enable --now firewalld
  ok "firewalld active (zone: $(firewall-cmd --get-default-zone 2>/dev/null || echo ?))"
else
  warn "firewalld left off. The 'sentinel' zone won't apply until it's enabled."
fi

# The broker runs in a container on :1883; the distro service must stay off.
if systemctl is-enabled --quiet mosquitto 2>/dev/null || systemctl is-active --quiet mosquitto 2>/dev/null; then
  warn "System mosquitto.service is enabled/running and would collide with the container on :1883."
  confirm "Disable the system mosquitto.service?" && sudo systemctl disable --now mosquitto
fi

sudo install -d -m 0755 /etc/containers/systemd
ok "/etc/containers/systemd (rootful Quadlet units)"

# --- Optional: full ESP-IDF for flashing from this box -----------------------
NEED_RELOGIN=0
if [[ $WITH_IDF == 1 ]]; then
  if ! user_in_group dialout; then
    info "Adding $USER to 'dialout' for serial ports"
    sudo usermod -aG dialout "$USER"
    NEED_RELOGIN=1
  fi
  "$REPO_ROOT/scripts/install-esp-idf.sh"
fi

# --- Python venv + esp_prov --------------------------------------------------
"$REPO_ROOT/scripts/setup-python-venv.sh"
[[ $WITH_PROV == 1 ]] && "$REPO_ROOT/scripts/install-esp-prov.sh"

# --- Readiness checks (non-fatal; host/scripts/probe-host.sh is the full probe) --
echo
info "Readiness checks"
check() { if eval "$2" >/dev/null 2>&1; then ok "$1"; else warn "$1: NOT OK. $3"; fi; }

pv="$(podman --version | awk '{print $3}')"
check "podman $pv supports Quadlet (>= 4.4)" \
  "printf '%s\n4.4\n' '$pv' | sort -V -C -r" "Upgrade podman."
check "Quadlet generator present" \
  "ls /usr/lib/systemd/system-generators/podman-system-generator" "Reinstall podman."
check "Intel iGPU render node /dev/dri/renderD128" \
  "test -e /dev/dri/renderD128" "No iGPU device; Frigate would fall back to the CPU detector."
check "i915/xe kernel driver loaded" \
  "lsmod | grep -Eq '^(i915|xe) '" "Check BIOS iGPU setting / kernel driver."
check "VAAPI usable (vainfo)" \
  "vainfo --display drm --device /dev/dri/renderD128" "Host VAAPI is diagnostic only; the Frigate image brings its own driver."
wifi_dev="$(nmcli -t -f DEVICE,TYPE device 2>/dev/null | awk -F: '$2=="wifi"{print $1; exit}')"
check "Wi-Fi device present (${wifi_dev:-none})" "test -n '$wifi_dev'" "No Wi-Fi device; see PLAN.md USB-UVC fallback."
check "Wi-Fi supports AP mode" \
  "iw list | grep -A12 'Supported interface modes' | grep -q '\\* AP\$'" \
  "No AP mode: run the host-probe escalation in docs/phases/README.md."
default_dev="$(ip route show default | awk '{for (i = 1; i < NF; i++) if ($i == "dev") { print $(i + 1); exit }}')"
check "Default route via ${default_dev:-none} (Ethernet, not Wi-Fi)" \
  "test -n '$default_dev' && test '$default_dev' != '${wifi_dev:-}'" \
  "Default route is on Wi-Fi or missing; the camera AP needs the Wi-Fi radio to itself."
check "Bluetooth controller powered" \
  "bluetoothctl show | grep -q 'Powered: yes'" "Try: bluetoothctl power on"
check "CPU has AVX2 (face recognition)" "grep -qw avx2 /proc/cpuinfo" "Face recognition needs AVX2."
info "CPU: $(lscpu | sed -n 's/^Model name:[[:space:]]*//p')"
info "Free space for recordings (/var): $(df -h --output=avail /var | tail -1 | tr -d ' ')"

echo
info "Fedora host dependencies installed."

# --- Deploy: secrets, hidden AP, services ------------------------------------
if [[ $DEPLOY == 1 ]]; then
  echo
  info "Secrets (generated once, kept in secrets/, never printed)"
  "$REPO_ROOT/host/scripts/generate-secrets.sh" --cameras "$CAMERAS"

  if [[ $DO_AP == 1 ]]; then
    echo
    info "Hidden camera AP"
    ap_args=()
    [[ -n "$IFACE" ]] && ap_args+=(--wifi-iface "$IFACE")
    [[ -n "$CHANNEL" ]] && ap_args+=(--channel "$CHANNEL")
    "$REPO_ROOT/host/network/install-ap.sh" "${ap_args[@]}"
  fi

  if [[ $DO_SERVICES == 1 ]]; then
    echo
    info "System services: mosquitto, Frigate, sentinel-controller (images are large; the first run takes a while)"
    if ! ip -4 -o addr show | grep -q ' 10\.77\.0\.1/24'; then
      warn "10.77.0.1 is not up (no AP). mosquitto will retry until it is; fix the AP stage and re-run."
    fi
    sudo "$REPO_ROOT/host/scripts/install-services.sh" --cameras "$CAMERAS"
  fi
fi

echo
info "Done."
[[ $NEED_RELOGIN == 1 ]] && warn "Log out and back in before flashing, for serial access."
if [[ $DEPLOY == 1 ]]; then
  cat <<EOF

Secrets: $SECRETS_DIR
  ap.env holds the SSID and passphrase; frigate-admin.txt holds Frigate's first admin login.
  Back this directory up somewhere private: losing it means reflashing every camera.

Next, flash the cameras (one board at a time, over USB). Each boots already bound: no BLE
step, no PoP to copy.
  - on this box:     scripts/install-fedora.sh --with-esp-idf    # once; log out/in for serial access
                     scripts/install-esp32.sh all
  - on the Arch box: scripts/install-esp32.sh all --from $USER@$(hostname -s)
                     (set SENTINEL_REMOTE_REPO=$REPO_ROOT if the checkout is elsewhere on this host)

Check:  systemctl status mosquitto frigate sentinel-controller
        https://127.0.0.1:8971   (Frigate UI, self-signed certificate)
EOF
else
  cat <<EOF

Deploy (secrets, hidden AP, services) was skipped: re-run scripts/install-fedora.sh without --no-deploy.
EOF
fi
