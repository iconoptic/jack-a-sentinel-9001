#!/usr/bin/env bash
# Pull pinned upstream documentation into docs/vendor/ (gitignored).
# Re-run any time. Versions are pinned in scripts/lib/versions.sh.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$ROOT/docs/vendor"
# shellcheck source=lib/versions.sh
. "$ROOT/scripts/lib/versions.sh"
IDF_EXTRA_REF="master"   # docs only; installs pin NETWORK_PROV_COMMIT instead

# sparse_clone <name> <repo-url> <ref> <pattern>...
sparse_clone() {
  local name="$1" url="$2" ref="$3"; shift 3
  local dir="$DEST/$name"
  rm -rf "$dir"
  git clone --quiet --depth 1 --branch "$ref" --filter=blob:none --no-checkout "$url" "$dir"
  git -C "$dir" sparse-checkout set --no-cone "$@"
  git -C "$dir" checkout --quiet
  printf '%s\t%s\t%s\t%s\n' "$name" "$url" "$ref" "$(git -C "$dir" rev-parse --short HEAD)" >> "$DEST/VERSIONS.tsv"
  rm -rf "$dir/.git"
}

fetch() { # fetch <relative-dest> <url>
  mkdir -p "$(dirname "$DEST/$1")"
  curl -fsSL --retry 3 -o "$DEST/$1" "$2"
  printf '%s\t%s\t-\t-\n' "$1" "$2" >> "$DEST/VERSIONS.tsv"
}

mkdir -p "$DEST"
printf 'name\tsource\tref\tcommit\n' > "$DEST/VERSIONS.tsv"

# Camera sensor driver (OV3660 support, pin config, frame buffer / JPEG tuning)
sparse_clone esp32-camera https://github.com/espressif/esp32-camera.git "$ESP32_CAMERA_REF" \
  '/README.md' '/Kconfig' '/driver/include/' '/examples/'

# BLE provisioning (Wi-Fi creds + custom endpoints, Security 2 / SRP6a)
sparse_clone network_provisioning https://github.com/espressif/idf-extra-components.git "$IDF_EXTRA_REF" \
  '/network_provisioning/README.md' '/network_provisioning/CHANGELOG.md' '/network_provisioning/Kconfig' \
  '/network_provisioning/include/' '/network_provisioning/examples/' '/network_provisioning/tool/'

# ESP-IDF: only the guides this project leans on
sparse_clone esp-idf https://github.com/espressif/esp-idf.git "$ESP_IDF_REF" \
  '/docs/en/get-started/linux-setup.rst' '/docs/en/get-started/eim-install-idf.rst' \
  '/docs/en/get-started/linux-macos-setup-legacy.rst' '/docs/en/get-started/establish-serial-connection.rst' \
  '/docs/en/get-started/flashing-troubleshooting.rst' '/docs/en/api-guides/inc/linux-host-requirements.rst' \
  '/docs/en/api-reference/protocols/esp_http_server.rst' \
  '/docs/en/api-reference/protocols/mqtt.rst' \
  '/docs/en/api-reference/protocols/mdns.rst' \
  '/docs/en/api-reference/storage/nvs_flash.rst' \
  '/docs/en/api-reference/storage/nvs_encryption.rst' \
  '/docs/en/api-reference/system/ota.rst' \
  '/docs/en/api-reference/system/esp_https_ota.rst' \
  '/docs/en/api-reference/bluetooth/nimble/' \
  '/docs/en/api-guides/wifi-driver/' \
  '/docs/en/api-guides/wifi-security.rst' \
  '/docs/en/security/' \
  '/examples/protocols/http_server/simple/' \
  '/examples/system/ota/simple_ota_example/'

# Host-side NVR: recording, detection, face recognition, MQTT, HTTP API
sparse_clone frigate https://github.com/blakeblackshear/frigate.git "$FRIGATE_REF" \
  '/docs/docs/' '/docs/static/frigate-api.yaml'

# Stream ingest/restream (bundled inside Frigate; MJPEG source docs live here)
sparse_clone go2rtc https://github.com/AlexxIT/go2rtc.git "$GO2RTC_REF" \
  '/README.md' '/internal/mjpeg/README.md' '/internal/http/README.md'

# Hardware references
fetch hardware/esp32-s3_datasheet_en.pdf \
  https://www.espressif.com/sites/default/files/documentation/esp32-s3_datasheet_en.pdf
fetch hardware/esp32-s3-wroom-1_wroom-1u_datasheet_en.pdf \
  https://www.espressif.com/sites/default/files/documentation/esp32-s3-wroom-1_wroom-1u_datasheet_en.pdf
# Closest documented clone of the FORIOT board (same N16R8 + OV3660 + CH340C/OTG layout)
fetch hardware/keyestudio-MB0200-S3-CAM.md \
  "https://docs.keyestudio.com/projects/MB0200/en/latest/_sources/docs/MB0200%20S3%20CAM.md.txt"

echo "Docs written to $DEST"
column -t -s $'\t' "$DEST/VERSIONS.tsv"
