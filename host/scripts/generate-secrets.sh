#!/usr/bin/env bash
# Generate every secret the deployment needs into the gitignored secrets/ tree:
#   - hidden-AP SSID (boring, random) and a random WPA2 passphrase
#   - MQTT passwords for frigate, controller and cam_a/b/c, plus the mosquitto ACL
#   - per-camera stream tokens
# Idempotent: existing values are kept, so re-running never breaks a deployed camera.
# WIFI_IFACE / CHANNEL / WIFI_BSSID in ap.env are filled by host/network/install-ap.sh.
#
#   host/scripts/generate-secrets.sh [--cameras a,b,c]
set -euo pipefail
. "$(dirname "${BASH_SOURCE[0]}")/../../scripts/lib/common.sh"
umask 077
provision_cli init "$@"
