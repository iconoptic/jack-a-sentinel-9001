# shellcheck shell=bash
# shellcheck disable=SC2034  # consumed by the scripts that source this file
# Single source of truth for pinned upstream versions. Sourced by scripts/*.sh.
# Bump deliberately, together with docs/PLAN.md "Pinned upstream versions".

ESP_IDF_REF="v6.0.3"
ESP_IDF_TARGETS="esp32s3"
ESP32_CAMERA_REF="v2.1.8"

# idf-extra-components has no per-component tags; this is the network_provisioning 1.3.1 release commit.
NETWORK_PROV_COMMIT="e9c0dd1830dc16f5e39c9695e24d669cd00b9fdb"

FRIGATE_REF="v0.18.1"
GO2RTC_REF="v1.9.14"

FRIGATE_IMAGE="ghcr.io/blakeblackshear/frigate:0.18.1"
MOSQUITTO_IMAGE="docker.io/library/eclipse-mosquitto:2"

# Python: ESP-IDF needs 3.10+, the host packages (pyproject) need 3.11+.
PY_MIN_MINOR=11
PY_MAX_MINOR=14
