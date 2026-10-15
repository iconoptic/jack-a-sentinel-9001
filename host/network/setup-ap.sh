#!/usr/bin/env bash
# Idempotent-ish hidden camera AP. Reads secrets/ap.env. Does not print the PSK.
# Does not enable DHCP, NAT, or forwarding.
set -euo pipefail

CON=sentinel-ap
AP_ADDR=10.77.0.1/24

script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=$(cd "$script_dir/../.." && pwd)
env_file=${SENTINEL_AP_ENV:-$repo_root/secrets/ap.env}
zone_src=$script_dir/sentinel-zone.xml

die() {
    printf '%s\n' "$1" >&2
    exit 1
}

if [[ "$(id -u)" -ne 0 ]]; then
    die "Run as root: sudo $0"
fi

[[ -f "$env_file" ]] || die "Missing $env_file. Run host/scripts/generate-secrets.sh, then set WIFI_IFACE and CHANNEL."
[[ -f "$zone_src" ]] || die "Missing $zone_src"

# shellcheck disable=SC1090
source "$env_file"

[[ -n "${WIFI_IFACE:-}" ]] || die "WIFI_IFACE is empty in $env_file"
[[ -n "${SSID:-}" ]] || die "SSID is empty in $env_file"
[[ -n "${PSK:-}" ]] || die "PSK is empty in $env_file"
[[ -n "${CHANNEL:-}" ]] || die "CHANNEL is empty in $env_file. Use 1, 6, or 11 after a scan."

case "$CHANNEL" in
    1|6|11) ;;
    *) die "CHANNEL must be 1, 6, or 11 (got $CHANNEL)" ;;
esac

if [[ "${SSID,,}" == *sentinel* ]]; then
    die "SSID must not contain SENTINEL"
fi

psk_len=${#PSK}
if (( psk_len < 8 || psk_len > 63 )); then
    die "PSK length must be 8–63 characters"
fi

case "$PSK" in
    REPLACE_ME|example-not-a-real-password) die "PSK is still the example placeholder" ;;
esac
case "$SSID" in
    REPLACE_ME) die "SSID is still the example placeholder" ;;
esac
case "$WIFI_IFACE" in
    REPLACE_ME) die "WIFI_IFACE is still the example placeholder" ;;
esac

command -v nmcli >/dev/null 2>&1 || die "nmcli is not installed"
command -v firewall-cmd >/dev/null 2>&1 || die "firewall-cmd is not installed"
command -v ip >/dev/null 2>&1 || die "ip is not installed"
ip link show "$WIFI_IFACE" >/dev/null 2>&1 || die "No interface named $WIFI_IFACE"

firewall-cmd --state >/dev/null 2>&1 || die "firewalld is not running"

# Saved Wi-Fi client profiles must not autoconnect or they will fight the AP.
blocked=0
while IFS= read -r name; do
    [[ -z "$name" ]] && continue
    ctype=$(nmcli -g connection.type connection show "$name" 2>/dev/null || true)
    [[ "$ctype" == "802-11-wireless" ]] || continue
    [[ "$name" == "$CON" ]] && continue
    autoconnect=$(nmcli -g connection.autoconnect connection show "$name")
    if [[ "$autoconnect" == "yes" ]]; then
        printf 'Wi-Fi profile %q still autoconnects. Disable it, then re-run:\n' "$name" >&2
        printf '  nmcli connection modify %q connection.autoconnect no\n' "$name" >&2
        blocked=1
    fi
done < <(nmcli -f NAME -m multiline connection show | sed -n 's/^NAME:[[:space:]]*//p')

if (( blocked != 0 )); then
    die "Client Wi-Fi profiles still autoconnect."
fi

active=$(nmcli -g GENERAL.CONNECTION device show "$WIFI_IFACE" 2>/dev/null || true)
case "$active" in
    ""|--|"$CON") ;;
    *)
        printf 'Interface %s is on connection %q. Disconnect it, then re-run:\n' "$WIFI_IFACE" "$active" >&2
        printf '  nmcli connection down %q\n' "$active" >&2
        exit 1
        ;;
esac

install -m 0644 "$zone_src" /etc/firewalld/zones/sentinel.xml
firewall-cmd --reload >/dev/null

if firewall-cmd --zone=sentinel --query-masquerade >/dev/null 2>&1; then
    firewall-cmd --permanent --zone=sentinel --remove-masquerade >/dev/null
    firewall-cmd --reload >/dev/null
fi

if nmcli -g connection.id connection show "$CON" >/dev/null 2>&1; then
    nmcli connection modify "$CON" connection.interface-name "$WIFI_IFACE" 802-11-wireless.ssid "$SSID"
else
    nmcli connection add type wifi ifname "$WIFI_IFACE" con-name "$CON" \
        ssid "$SSID" \
        802-11-wireless.mode ap \
        connection.autoconnect no >/dev/null
fi

# cloned-mac-address permanent keeps the AP's BSSID equal to the radio's own MAC, so the
# BSSID recorded in secrets/ap.env (and pinned in camera firmware) survives reboots.
# wpa-psk with proto rsn and pmf disabled is WPA2-PSK. WPA3 transition mode
# and required PMF break the ESP32 station firmware.
nmcli connection modify "$CON" \
    connection.autoconnect yes \
    connection.zone sentinel \
    802-11-wireless.mode ap \
    802-11-wireless.band bg \
    802-11-wireless.channel "$CHANNEL" \
    802-11-wireless.channel-width 20mhz \
    802-11-wireless.hidden yes \
    802-11-wireless.powersave disable \
    802-11-wireless.cloned-mac-address permanent \
    802-11-wireless.mac-address-randomization never \
    connection.autoconnect-priority 100 \
    802-11-wireless-security.key-mgmt wpa-psk \
    802-11-wireless-security.proto rsn \
    802-11-wireless-security.pairwise ccmp \
    802-11-wireless-security.group ccmp \
    802-11-wireless-security.pmf disable \
    802-11-wireless-security.psk "$PSK" \
    ipv4.method manual \
    ipv4.addresses "$AP_ADDR" \
    ipv4.gateway "" \
    ipv4.dns "" \
    ipv4.never-default yes \
    ipv6.method disabled

nmcli connection up "$CON" >/dev/null

require_prop() {
    local key=$1 expected=$2 actual
    actual=$(nmcli -g "$key" connection show "$CON")
    actual=${actual%% *}
    case "$key:$actual" in
        802-11-wireless-security.pmf:1) actual=disable ;;
        ipv4.never-default:true|ipv4.never-default:on) actual=yes ;;
        802-11-wireless.hidden:true|802-11-wireless.hidden:on) actual=yes ;;
    esac
    if [[ "$actual" != "$expected" ]]; then
        printf 'Property %s is %q, expected %q\n' "$key" "$actual" "$expected" >&2
        nmcli connection down "$CON" >/dev/null || true
        exit 1
    fi
}

require_prop ipv4.method manual
require_prop ipv4.never-default yes
require_prop 802-11-wireless.mode ap
require_prop 802-11-wireless.hidden yes
require_prop 802-11-wireless.cloned-mac-address permanent
require_prop 802-11-wireless.band bg
require_prop 802-11-wireless.channel "$CHANNEL"
require_prop connection.zone sentinel
require_prop ipv6.method disabled
require_prop 802-11-wireless-security.key-mgmt wpa-psk
require_prop 802-11-wireless-security.pmf disable

if ! ip -4 -o addr show dev "$WIFI_IFACE" | awk '{print $4}' | grep -qx '10.77.0.1/24'; then
    echo "Expected 10.77.0.1/24 on $WIFI_IFACE" >&2
    ip -4 addr show dev "$WIFI_IFACE" >&2
    nmcli connection down "$CON" >/dev/null || true
    exit 1
fi

if ip -4 route show default | grep -Eq "dev ${WIFI_IFACE}( |$)"; then
    echo "Default route is on the AP interface. Tearing the AP down." >&2
    ip -4 route show default >&2
    nmcli connection down "$CON" >/dev/null || true
    exit 1
fi

zone=$(firewall-cmd --get-zone-of-interface="$WIFI_IFACE" 2>/dev/null || true)
if [[ "$zone" != "sentinel" ]]; then
    printf 'Interface %s is in firewalld zone %q, expected sentinel\n' "$WIFI_IFACE" "$zone" >&2
    exit 1
fi

printf 'AP connection %s is up on %s at 10.77.0.1/24 (hidden, channel %s).\n' "$CON" "$WIFI_IFACE" "$CHANNEL"
printf 'Default route:\n'
ip -4 route show default
printf 'net.ipv4.ip_forward=%s (this script does not change it and does not add masquerade)\n' "$(sysctl -n net.ipv4.ip_forward)"
printf 'firewalld zone sentinel:\n'
firewall-cmd --zone=sentinel --list-all
if command -v iw >/dev/null 2>&1; then
    printf 'Record addr (BSSID) and channel for a later bind payload. Do not commit them.\n'
    iw dev "$WIFI_IFACE" info || true
fi
printf 'Next: phone test in host/network/README.md. Ethernet must stay the default route.\n'
