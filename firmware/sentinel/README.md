# Sentinel firmware (Phase 3)

ESP-IDF v6.0.3 product firmware for the ESP32-S3 camera boards. Wire formats match
[docs/phases/CONTRACTS.md](../../docs/phases/CONTRACTS.md).

## One-click install

```bash
scripts/install-esp32.sh a        # b, c, or all; run from the repo root
```

Builds this project, bakes the camera's bind data (including the hidden AP's SSID and
passphrase) into an encrypted NVS image, and flashes bootloader, app, NVS and key in one
step. The board boots **BOUND** (no BLE, no PoP). See the repo [README](../../README.md#setup).

How it fits the firmware: the bind NVS namespace carries two optional keys, `wifi_ssid` and
`wifi_psk`. When present the board connects with them. When absent (BLE-bound boards) it falls
back to the credentials `network_provisioning` stored in the `esp_wifi` namespace. The NVS key
partition is generated per camera on first flash and kept in `secrets/cameras/<id>.nvs-keys.bin`;
`sentinel_nvs_init()` picks it up unchanged.

## Build

```bash
source ~/Projects/jack-a-sentinel_9001/scripts/idf-env.sh   # or ~/.config/jack-sentinel/env.sh
cd firmware/sentinel
idf.py set-target esp32s3
idf.py build
idf.py -p /dev/ttyUSB0 flash monitor
```

## Host unit tests (bind JSON + cmd parsing)

```bash
cd firmware/sentinel/host_test
cmake -B build && cmake --build build && ctest --test-dir build
```

## Human verification

1. **Fresh flash:** Serial shows BLE PoP once (username `sentinel`). Board advertises
   `SENTINEL-XXXX`. Use Phase 4 `sentinel-provision` (or `esp_prov`) with Security 2.
2. **After bind:** `GET http://<static_ip>/stream?token=<stream_token>` returns MJPEG.
   MQTT telemetry on `sentinel/<id>/telemetry` every 30 s.
3. **Reboot:** No BLE advertising; camera reconnects with stored bind + Wi-Fi creds.
4. **Factory reset:** Hold **BOOT** for 10 s during power-up → UNBOUND, BLE returns.

## Wave B hardware gate

Boot log must show **OV3660** (`PID 0x3660`), **16 MB flash**, and **octal PSRAM**.
If your Phase 1 log differs, stop and reconcile pinout in [docs/hardware.md](../../docs/hardware.md)
before shipping boards.

## Modules

| Component | Role |
| --- | --- |
| `sentinel_bind` | `sentinel-bind` JSON, NVS namespace `bind`, state machine |
| `sentinel_prov` | BLE `network_provisioning` Security 2 + custom endpoint |
| `sentinel_stream` | Authenticated `/stream` and `/snapshot` |
| `sentinel_mqtt` | LWT, telemetry, idle/armed commands with TTL |
