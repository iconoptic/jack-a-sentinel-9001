# Phase 1: Bench bring-up (one board)

**Kind:** coding agent prompt  
**Model:** Composer 2.5 Fast (`composer-2.5-fast`)  
**Wave:** A (parallel with Phase 2 and Phase 4 controller)  
**Parent plan:** [../PLAN.md](../PLAN.md#phase-1-bench-bring-up-one-board)

## Agent instructions

You are implementing Phase 1 only. Read [CONTRACTS.md](CONTRACTS.md) and
[../hardware.md](../hardware.md) before editing. Do not invent a pinout. Do not
start Phase 2–6. Do not create `firmware/sentinel/` (that is Phase 3).

## Goal

Create a throwaway ESP-IDF bring-up project that streams MJPEG from one board so
a human can measure fps, temperature, and confirm the sensor and PSRAM.

## Already decided

- ESP-IDF **v6.0.3** on the **Arch** dev machine (not the Fedora box).
- Board pinout: ESP32-S3-EYE layout in [../hardware.md](../hardware.md).
- Octal PSRAM: `CONFIG_SPIRAM_MODE_OCT=y`.
- Camera component: `espressif/esp32-camera` **2.1.8** (see
  [../vendor/VERSIONS.tsv](../vendor/VERSIONS.tsv) after fetch).
- Product resolution default remains HD per CONTRACTS.md until measurements say
  otherwise. This phase still measures VGA, SVGA, HD, UXGA.
- Wi-Fi credentials for bench: untracked file under `secrets/` or
  `firmware/bringup/wifi.local` (gitignored via existing `secrets/` / do not commit
  PSK). Hardcoded at build/config time for bring-up is fine; no BLE yet.
- Stream: basic `GET /stream` MJPEG. Auth optional in bring-up; Phase 3 adds tokens.

## Files to create

```text
firmware/bringup/
  README.md                 how to build, flash, open serial, fill measurement sheet
  CMakeLists.txt
  sdkconfig.defaults        Octal PSRAM, ESP32-S3, camera-friendly defaults
  main/
    CMakeLists.txt
  idf_component.yml         pin esp32-camera 2.1.8
  MEASUREMENTS.md           table for human: resolution, fps, temp, notes
```

Follow existing [../../firmware/README.md](../../firmware/README.md): bring-up lives
in `bringup/` and may be thrown away later.

## Behavior requirements

1. Initialize the camera with the ESP32-S3-EYE pinout from hardware.md.
2. Join Wi-Fi from the untracked creds file (document the expected keys in README).
3. Serve `GET /stream` as `multipart/x-mixed-replace` MJPEG.
4. Every few seconds on serial, print one line with at least: sensor PID, current
   framesize, measured fps, free heap, free PSRAM, chip temperature (if available).
5. `MEASUREMENTS.md` has rows for VGA 640×480, SVGA 800×600, HD 1280×720, UXGA
   1600×1200 (or max available), columns for fps, JPEG quality used, temperature
   after 30 min continuous stream, and pass/fail for "stable enough for product".

## Out of scope

- BLE provisioning, bind NVS, MQTT, idle/armed modes, stream tokens
- Frigate, go2rtc, host AP
- Changing CONTRACTS.md resolution unless you are the Grok escalation (you are not)

## Verify

1. If `docs/vendor/` is missing, run `./scripts/fetch-docs.sh` (needs network).
2. If ESP-IDF v6.0.3 is installed (`. scripts/idf-env.sh` succeeds): `idf.py set-target esp32s3`
   and `idf.py build` must succeed.
3. If ESP-IDF is not installed: stop after the project files exist. Point the human
   at `scripts/install-arch.sh` (then `. scripts/idf-env.sh`). Do not install IDF
   unless the user asks in this chat.
4. Do **not** require a board for the agent exit. Flash, port labeling, and the
   24 h soak are human steps.

## Human steps after the agent (for the Wave B gate)

Paste into the Wave B prompts (Phase 3 and Phase 4 provision CLI):

- `esptool chip-id` / `flash-id` (expect ESP32-S3, 16 MB flash)
- Boot log line showing 8 MB octal PSRAM
- Sensor PID (expect OV3660 `0x3660`)
- Which USB-C is CH340 vs native (label them)

Fill `MEASUREMENTS.md` and the checklist in [../hardware.md](../hardware.md).

**If PID is not `0x3660`, or HD cannot hold a stable stream without thermal
throttling:** stop Wave B firmware assumptions and run the Grok resolution
escalation in [README.md](README.md) before Phase 3.

## Exit (phase done)

One camera streams stably for **24 h** on the bench (human). Agent exit is earlier:
project builds (or IDF missing with clear install pointer) and measurement sheet
exists.

## Stop conditions

- Stop if hardware.md pinout and the Keyestudio clone docs disagree in a way you
  cannot resolve without guessing. Ask the human; do not invent GPIOs.
- Stop after build success (or IDF-missing note). Do not start Phase 3.
