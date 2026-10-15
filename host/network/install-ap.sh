#!/usr/bin/env bash
# Stand up the hidden camera AP end to end (RUNBOOK steps 1-3), as your normal user:
#   1. pick the Wi-Fi interface that supports AP mode          -> secrets/ap.env WIFI_IFACE
#   2. scan and pick the quietest of channels 1 / 6 / 11       -> secrets/ap.env CHANNEL
#   3. turn off autoconnect on saved Wi-Fi *client* profiles (the radio is the AP's alone)
#   4. sudo host/network/setup-ap.sh  (NetworkManager profile `sentinel-ap`, firewalld zone)
#   5. record the AP's BSSID                                    -> secrets/ap.env WIFI_BSSID
#
#   host/network/install-ap.sh [--wifi-iface IF] [--channel 1|6|11] [-y]
#
# Needs secrets/ap.env (host/scripts/generate-secrets.sh). The NetworkManager profile
# autoconnects, so the AP comes back by itself after every reboot. Idempotent: if the AP is
# already up with the right SSID, channel and passphrase, nothing is touched.
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/lib/common.sh"
require_not_root

CON=sentinel-ap
IFACE="" CHANNEL=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --wifi-iface) IFACE="${2:?}"; shift ;;
    --channel)    CHANNEL="${2:?}"; shift ;;
    -y|--yes)     export ASSUME_YES=1 ;;
    -h|--help)    sed -n '2,15p' "$0"; exit 0 ;;
    *)            die "Unknown option: $1" ;;
  esac
  shift
done

have nmcli && have iw && have ip || die "nmcli, iw and ip are required (scripts/install-fedora.sh installs them)."
[[ -f "$SECRETS_DIR/ap.env" ]] || die "No secrets/ap.env. Run host/scripts/generate-secrets.sh first."

default_dev() { ip -4 route show default | awk '{for (i = 1; i < NF; i++) if ($i == "dev") { print $(i + 1); exit }}'; }

supports_ap() {   # supports_ap IFACE
  local phy
  phy="$(iw dev "$1" info 2>/dev/null | awk '$1 == "wiphy" { print "phy" $2; exit }')"
  [[ -n "$phy" ]] && iw "$phy" info 2>/dev/null | awk '/Supported interface modes/{f=1;next} f&&/^\t\t \* /{print $2; next} f{exit}' | grep -qx AP
}

# --- 1. Interface -------------------------------------------------------------
[[ -n "$IFACE" ]] || IFACE="$(ap_env_get WIFI_IFACE)"
if [[ -z "$IFACE" ]]; then
  dflt="$(default_dev)"
  candidates=()
  while IFS=: read -r dev type; do
    [[ "$type" == wifi ]] || continue
    [[ "$dev" == "$dflt" ]] && continue
    supports_ap "$dev" && candidates+=("$dev")
  done < <(nmcli -t -f DEVICE,TYPE device)
  case ${#candidates[@]} in
    0) die "No Wi-Fi interface with AP mode (and not carrying the default route). See docs/phases/README.md host-probe escalation." ;;
    1) IFACE="${candidates[0]}" ;;
    *) IFACE="${candidates[0]}"; warn "Several AP-capable interfaces (${candidates[*]}); using $IFACE. Override with --wifi-iface." ;;
  esac
fi
ip link show "$IFACE" >/dev/null 2>&1 || die "No interface named $IFACE"
supports_ap "$IFACE" || die "$IFACE does not list AP among its supported interface modes."
ok "AP interface: $IFACE"

# The AP must never take over the route to the rest of the network.
if [[ "$(default_dev)" == "$IFACE" ]]; then
  die "The default route is on $IFACE. Connect Ethernet first: the Wi-Fi radio becomes the camera AP and would cut you off."
fi

# --- 2. Channel ---------------------------------------------------------------
if [[ -z "$CHANNEL" ]]; then
  CHANNEL="$(ap_env_get CHANNEL)"
fi
if [[ -z "$CHANNEL" ]]; then
  info "Scanning 2.4 GHz for the quietest of channels 1, 6, 11"
  scan="$(nmcli -t -f CHAN,SIGNAL device wifi list ifname "$IFACE" --rescan yes 2>/dev/null || true)"
  CHANNEL="$(awk -F: '
    $1 >= 1 && $1 <= 13 { ch[NR] = $1; sig[NR] = $2; n = NR }
    END {
      split("1 6 11", cand, " "); best = 6; min = -1
      for (c = 1; c <= 3; c++) {
        score = 0
        for (i = 1; i <= n; i++) {
          d = ch[i] - cand[c]; if (d < 0) d = -d
          if (d < 5) score += sig[i] * (5 - d) / 5
        }
        if (min < 0 || score < min) { min = score; best = cand[c] }
      }
      print best
    }' <<<"$scan")"
  if [[ -z "$scan" ]]; then
    warn "Scan returned nothing; defaulting to channel 6."
    CHANNEL=6
  fi
fi
case "$CHANNEL" in 1|6|11) ;; *) die "Channel must be 1, 6 or 11 (got '$CHANNEL')." ;; esac
ok "Channel: $CHANNEL"

provision_cli ap-set "WIFI_IFACE=$IFACE" "CHANNEL=$CHANNEL" >/dev/null

# --- 3. Client profiles on that radio -------------------------------------------
declare -a clients=()
# UUIDs avoid nmcli's escaping of ':' in profile names.
while IFS=: read -r uuid type; do
  [[ "$type" == 802-11-wireless ]] || continue
  { read -r name; read -r auto; } < <(nmcli -g connection.id,connection.autoconnect connection show uuid "$uuid")
  [[ "$name" != "$CON" && "$auto" == yes ]] && clients+=("$name")
done < <(nmcli -t -f UUID,TYPE connection show)
if ((${#clients[@]})); then
  warn "Saved Wi-Fi client profiles that would fight the AP for the radio: ${clients[*]}"
  confirm "Turn off autoconnect for them (they stay saved)?" \
    || die "Declined. Disable them yourself (nmcli connection modify NAME connection.autoconnect no) and re-run."
  for c in "${clients[@]}"; do
    nmcli connection modify "$c" connection.autoconnect no
    if [[ "$(nmcli -g GENERAL.CONNECTION device show "$IFACE" 2>/dev/null)" == "$c" ]]; then
      nmcli connection down "$c" >/dev/null
    fi
    ok "autoconnect off: $c"
  done
fi

# --- 4. The AP ------------------------------------------------------------------
ap_matches() {
  [[ "$(nmcli -g GENERAL.STATE connection show "$CON" 2>/dev/null)" == activated* ]] || return 1
  [[ "$(nmcli -g 802-11-wireless.ssid connection show "$CON")" == "$(ap_env_get SSID)" ]] || return 1
  [[ "$(nmcli -g 802-11-wireless.channel connection show "$CON")" == "$CHANNEL" ]] || return 1
  [[ "$(sudo nmcli -s -g 802-11-wireless-security.psk connection show "$CON")" == "$(ap_env_get PSK)" ]] || return 1
}
if ap_matches; then
  ok "AP $CON already up with these settings"
else
  info "Creating the hidden AP (sudo)"
  sudo "$REPO_ROOT/host/network/setup-ap.sh" >/dev/null
  ok "AP $CON is up (hidden, 2.4 GHz channel $CHANNEL, WPA2-PSK, 10.77.0.1/24, no NAT, no DHCP)"
fi

# --- 5. BSSID for the camera firmware -------------------------------------------
bssid=""
for _ in 1 2 3 4 5; do
  bssid="$(iw dev "$IFACE" info | awk '$1 == "addr" { print $2; exit }')"
  [[ -n "$bssid" ]] && break
  sleep 1
done
[[ -n "$bssid" ]] || die "Could not read the AP's BSSID from 'iw dev $IFACE info'."
if [[ -n "$(ap_env_get WIFI_BSSID)" && "$(ap_env_get WIFI_BSSID)" != "${bssid,,}" ]]; then
  warn "BSSID changed ($(ap_env_get WIFI_BSSID) -> $bssid). Cameras flashed with the old one must be reflashed."
fi
provision_cli ap-set "WIFI_BSSID=$bssid" >/dev/null
ok "BSSID recorded in secrets/ap.env"

# Same checks RUNBOOK step 3 asks for.
if ip -4 route show default | grep -Eq "dev ${IFACE}( |$)"; then
  die "Default route moved onto $IFACE. Bring the AP down: nmcli connection down $CON"
fi
ok "Ethernet is still the default route ($(default_dev))"
