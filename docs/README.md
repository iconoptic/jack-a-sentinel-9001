# Docs index

Project docs:

- [PLAN.md](PLAN.md): architecture and implementation plan
- [hardware.md](hardware.md): board, pinout and host notes
- [phases/README.md](phases/README.md): per-phase implementer briefs (models, waves, prompts)
- [phases/CONTRACTS.md](phases/CONTRACTS.md): frozen network / bind / MQTT / Frigate interfaces
- [phases/REVIEW-HANDOFF.md](phases/REVIEW-HANDOFF.md): reviewer prompt that audits the build and writes fix plans

Upstream docs live in `vendor/`. They are pulled at pinned versions by
[`../scripts/fetch-docs.sh`](../scripts/fetch-docs.sh) and are not committed.
`vendor/VERSIONS.tsv` records exactly what was fetched.

## Where to look

| Topic | Local path (under `docs/vendor/`) | Upstream |
| --- | --- | --- |
| Camera driver: `camera_config_t`, frame sizes, JPEG quality, PSRAM frame buffers | `esp32-camera/README.md`, `esp32-camera/driver/include/` | [espressif/esp32-camera](https://github.com/espressif/esp32-camera) |
| Camera example (HTTP JPEG/MJPEG server) | `esp32-camera/examples/` | same |
| BLE provisioning, Security 2 (SRP6a), custom endpoints | `network_provisioning/network_provisioning/README.md`, `.../include/network_provisioning/manager.h` | [idf-extra-components/network_provisioning](https://github.com/espressif/idf-extra-components/tree/master/network_provisioning) |
| Host-side provisioning client (`esp_prov`) | `network_provisioning/network_provisioning/tool/esp_prov/` | same |
| ESP-IDF install on Linux (scripted: `scripts/install-esp-idf.sh`) | `esp-idf/docs/en/get-started/linux-macos-setup-legacy.rst` (method used), `linux-setup.rst` (EIM), `establish-serial-connection.rst` | [ESP-IDF docs](https://docs.espressif.com/projects/esp-idf/en/v6.0.3/esp32s3/) |
| HTTP server (stream + control endpoints) | `esp-idf/docs/en/api-reference/protocols/esp_http_server.rst`, `esp-idf/examples/protocols/http_server/simple/` | same |
| MQTT client | `esp-idf/docs/en/api-reference/protocols/mqtt.rst` | same |
| NVS + NVS encryption (bind secrets) | `esp-idf/docs/en/api-reference/storage/nvs_*.rst` | same |
| OTA updates | `esp-idf/docs/en/api-reference/system/ota.rst`, `esp_https_ota.rst`, `esp-idf/examples/system/ota/` | same |
| Wi-Fi driver, reconnect, WPA3 | `esp-idf/docs/en/api-guides/wifi-driver/`, `wifi-security.rst` | same |
| Flash encryption / Secure Boot v2 (**burns eFuses, irreversible**) | `esp-idf/docs/en/security/` | same |
| Frigate: cameras, MJPEG sources | `frigate/docs/docs/configuration/cameras.md`, `camera_specific.md` (§ MJPEG Cameras) | [docs.frigate.video](https://docs.frigate.video) |
| Frigate: recording, pre/post capture, retention | `frigate/docs/docs/configuration/record.md`, `review.md` | same |
| Frigate: face recognition | `frigate/docs/docs/configuration/face_recognition.md` | same |
| Frigate: detectors (CPU / OpenVINO / etc.) | `frigate/docs/docs/configuration/object_detectors.md` | same |
| Frigate: MQTT topics (`frigate/reviews`, `<cam>/motion`) | `frigate/docs/docs/integrations/mqtt.md` | same |
| Frigate: HTTP API (manual events) | `frigate/docs/static/frigate-api.yaml` (`/events/{camera}/{label}/create`, `/events/{id}/end`) | same |
| Frigate: install | `frigate/docs/docs/frigate/installation.md` | same |
| go2rtc: MJPEG ingest/restream | `go2rtc/README.md`, `go2rtc/internal/mjpeg/README.md` | [AlexxIT/go2rtc](https://github.com/AlexxIT/go2rtc) |
| ESP32-S3 SoC / WROOM-1 module datasheets | `hardware/*.pdf` | [espressif.com](https://www.espressif.com/en/support/documents/technical-documents) |
| Closest board clone (pinout source) | `hardware/keyestudio-MB0200-S3-CAM.md` | [Keyestudio MB0200](https://docs.keyestudio.com/projects/MB0200/en/latest/docs/MB0200%20S3%20CAM.html) |

Not vendored, but useful:

- ESP32-S3 Technical Reference Manual (very large): <https://www.espressif.com/sites/default/files/documentation/esp32-s3_technical_reference_manual_en.pdf>
- Podman Quadlet (systemd units for containers): `man podman-systemd.unit` on the Fedora box
- NetworkManager hotspot: `man nmcli-examples` (search for "hotspot")
- esptool: <https://docs.espressif.com/projects/esptool/>
