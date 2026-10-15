# Phase 1 bench bring-up

Throwaway ESP-IDF project: one board joins bench Wi-Fi and serves MJPEG on
`GET /stream`. Pinout is the ESP32-S3-EYE layout in
[docs/hardware.md](../../docs/hardware.md). Product firmware is Phase 3
(`firmware/sentinel/`).

## Prerequisites

- **ESP-IDF v6.0.3** on the Arch dev machine: run `scripts/install-arch.sh` once, then
  `. scripts/idf-env.sh` in each new shell. Background:
  [linux-macos-setup-legacy.rst](../../docs/vendor/esp-idf/docs/en/get-started/linux-macos-setup-legacy.rst)
  (run `./scripts/fetch-docs.sh` first if `docs/vendor/` is empty).
- USB-C **CH340** port for flash and serial (label ports after first boot — see
  [hardware checklist](../../docs/hardware.md#things-to-verify-on-real-hardware-phase-1)).

## Wi-Fi credentials (not in git)

Copy the example and edit:

```bash
cp wifi.local.example wifi.local
# SSID=... and PSK=... (see keys in wifi.local.example)
```

Alternatively put the same two lines in `secrets/bringup-wifi.local` and symlink
`wifi.local` to it. Values are baked in at **build** time via `main/CMakeLists.txt`.

## Build and flash

```bash
cd firmware/bringup
cp wifi.local.example wifi.local   # if not done yet — edit SSID/PSK
idf.py set-target esp32s3
idf.py build
idf.py -p /dev/ttyUSB0 flash monitor
```

Default framesize is HD. Change per measurement row with menuconfig
(`Component config` → `Sentinel bringup`) or at runtime:
`http://<board-ip>/framesize?vga|svga|hd|uxga` (then reload `/stream`).

## Stream and serial

- Browser or `ffplay`: `http://<board-ip>/stream` (`multipart/x-mixed-replace` MJPEG).
- Every ~3 s the console prints: sensor PID, framesize, fps, free heap, free PSRAM,
  on-chip temperature (when available).

Copy boot evidence for Wave B (before the 24 h soak completes):

- `esptool.py chip-id` / `flash-id` — expect ESP32-S3, **16 MB** flash
- Boot log — **8 MB octal PSRAM**
- Sensor PID — expect **0x3660**
- Which USB-C is CH340 vs native OTG

Record fps/temperature in [MEASUREMENTS.md](MEASUREMENTS.md) and the checklist in
[hardware.md](../../docs/hardware.md).

## Dependencies

- `espressif/esp32-camera` **2.1.8** (root [idf_component.yml](idf_component.yml))
- Octal PSRAM defaults in [sdkconfig.defaults](sdkconfig.defaults)
