# Phase 3: Sentinel firmware v1

**Kind:** coding agent prompt  
**Model:** Composer 2.5 Fast (`composer-2.5-fast`)  
**Wave:** B (after human pastes Phase 1 chip / PSRAM / sensor PID; parallel with Phase 4 provision CLI)  
**Parent plan:** [../PLAN.md](../PLAN.md#phase-3-sentinel-firmware-v1)

## Agent instructions

You are implementing Phase 3 only. Read [CONTRACTS.md](CONTRACTS.md) completely
before coding. Obey every HTTP, MQTT, bind, and network field name there. Do not
invent a second protocol. Do not implement OTA, MQTT TLS, or flash encryption
(Phase 6).

**Required human paste (Wave B gate):** chip id, flash size, octal PSRAM confirmed,
sensor PID. If PID is not `0x3660`, or the human says pinout differs from
[../hardware.md](../hardware.md), **stop** and ask; do not guess.

## Goal

Ship `firmware/sentinel/`: BLE Security 2 provisioning, one-host bind, then Wi-Fi
MJPEG + MQTT with idle/armed modes, matching CONTRACTS.md.

## Already decided

- ESP-IDF v6.0.3; `espressif/esp32-camera` 2.1.8; `network_provisioning` 1.3.x
  (pin in `idf_component.yml`, commit `dependencies.lock`).
- Pinout: ESP32-S3-EYE from hardware.md; Octal PSRAM.
- Resolution: HD idle/armed per CONTRACTS.md unless Grok already edited that section.
- State machine: UNBOUND → BOUND via successful Wi-Fi provision + `sentinel-bind`;
  BOOT held 10 s at power-up → UNBOUND (publish `factory_reset` if possible).
- After bind: `network_prov_mgr_deinit()`, release BT memory; never advertise again
  until factory reset.
- Stream auth, MQTT topics, telemetry, cmd TTL: CONTRACTS.md.
- Unit tests: bind state machine and command parsing on ESP-IDF Linux target where
  possible.

## Files to create

```text
firmware/sentinel/
  README.md
  CMakeLists.txt
  sdkconfig.defaults
  partitions.csv              include NVS encryption-capable layout as needed
  idf_component.yml
  dependencies.lock           after first successful component resolve
  main/
    …                         app entry, wifi, http stream, mqtt, bind, reset
  components/ or main modules:
    bind/                     NVS encrypted namespace `bind`, state machine
    prov/                     BLE + custom endpoint sentinel-bind
    stream/                   /stream /snapshot
    mqtt_cmd/                 telemetry, LWT, cmd parser
  test/ or host_test/         Linux-target tests for bind + cmd parsing
```

Structure may vary; keep modules testable. Update [../../firmware/README.md](../../firmware/README.md)
to point at `sentinel/` when present.

## Behavior checklist

- [ ] UNBOUND: advertise `SENTINEL-xxxx`, Security 2, PoP from flash-time generation
      printed once on serial
- [ ] Standard Wi-Fi creds endpoint + custom `sentinel-bind` JSON (CONTRACTS fields)
- [ ] Encrypted NVS `bind`; secrets never logged at info level
- [ ] Authenticated `/stream` and `/snapshot`
- [ ] MQTT state LWT, telemetry 30 s, cmd idle/armed with TTL fallback
- [ ] Task watchdog; Wi-Fi reconnect exponential backoff; reboot after N camera errors;
      brownout detector on
- [ ] Idle ~5 fps quality ~15; armed higher fps/quality; **same** framesize
- [ ] Armed auto-idle if TTL not refreshed

## Out of scope

- `sentinel-provision` CLI and Frigate config edits (Phase 4)
- OTA, TLS CA in bind, Secure Boot, flash encryption
- Changing camera IPs or topic names

## Verify

1. `idf.py build` for `esp32s3` succeeds.
2. Linux-target / host unit tests for bind transitions and cmd JSON pass.
3. Document human flash checks in README:
   - Fresh flash → BLE visible → bind → stream with token
   - Reboot → no BLE advertise
   - BOOT-hold 10 s at power-up → UNBOUND again

## Exit (phase done)

Human: freshly flashed board appears over BLE; after binding it streams; after reboot
it never advertises; BOOT-hold returns to UNBOUND. Agent exit: build + unit tests green,
README documents the human checks.

## Stop conditions

- Sensor PID ≠ `0x3660` or pinout conflict: stop.
- Missing Wave B paste: ask once, then stop.
- Do not start Phase 4 or 6 in this chat.
