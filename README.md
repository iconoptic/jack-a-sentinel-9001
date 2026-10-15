# jack-a-sentinel 9001

Three ESP32-S3-CAM boards plus an always-on Fedora box, watching one cubicle.
When a person shows up on any camera, all three keep footage, including the
seconds before the trigger.

**Status:** installable end to end. Two scripts and one flash per camera; see [Setup](#setup). Architecture: [docs/PLAN.md](docs/PLAN.md).

## How it works

```text
  sentinel-a/b/c (ESP32-S3 + OV3660)               Fedora host
  ──────────────────────────────────               ─────────────────────────────────────
                                   BLE, once
  provisioning + bind  ◄─────────────────────────  provisioning CLI

                                   Wi-Fi (private AP)
  HTTP MJPEG /stream   ─────────────────────────►  go2rtc ─► Frigate
                                                     person detect → face detect/recognize
                                                     rolling recording, alerts
  MQTT telemetry + LWT ─────────────────────────►  mosquitto ◄─► sentinel-controller
  MQTT mode commands   ◄─────────────────────────    cross-camera trigger, tamper events,
                                                     evidence export
```

- **BLE is used only to bind each camera to the host.** The ESP32-S3 has Bluetooth LE
  only, which is far too slow for video. After the first host binds, the camera stops
  advertising for good. Re-pairing needs physical access to the board.
- **Video goes over Wi-Fi** to a private access point that the Fedora box runs.
- **Recording and detection run on the host**, in [Frigate](https://frigate.video).
  The host keeps a rolling buffer, so a trigger can save footage from *before* the event.

## Layout

| Path | What |
| --- | --- |
| [docs/PLAN.md](docs/PLAN.md) | Architecture, decisions, phased implementation plan |
| [docs/phases/README.md](docs/phases/README.md) | Per-phase implementer briefs (models, parallel waves) |
| [docs/phases/CONTRACTS.md](docs/phases/CONTRACTS.md) | Frozen bind / MQTT / Frigate interfaces for agents |
| [docs/hardware.md](docs/hardware.md) | Board notes, camera pinout, ports, things to verify |
| [docs/README.md](docs/README.md) | Index into the vendored upstream docs |
| [scripts/fetch-docs.sh](scripts/fetch-docs.sh) | Pulls pinned upstream docs into `docs/vendor/` (gitignored) |
| [firmware/](firmware/) | ESP-IDF firmware for the cameras |
| [host/](host/) | Fedora AP, mosquitto, Frigate, Quadlet units. Runbook: [host/RUNBOOK.md](host/RUNBOOK.md). Live AP and detection checks are still a person on Fedora. |

## Setup

Each machine runs one script (idempotent, safe to re-run). Pinned versions live in
[scripts/lib/versions.sh](scripts/lib/versions.sh).

| Step | Machine | Command | Result |
| --- | --- | --- | --- |
| 1 | Fedora host (cubicle) | `scripts/install-fedora.sh` | Packages, **generated secrets**, the **hidden camera AP** (NetworkManager profile `sentinel-ap`, autoconnects at boot), and mosquitto, Frigate and sentinel-controller as **system services** (rootful Quadlet, images pinned by digest, enabled at boot). |
| 2 | Arch dev box (or the Fedora host with `--with-esp-idf`) | `scripts/install-arch.sh --flash all --from you@fedora-host` | ESP-IDF v6.0.3, serial access, venv; pulls the camera secrets over SSH; builds the firmware and flashes cameras a, b, c. |

Or flash on its own, any time: `scripts/install-esp32.sh a` (then `b`, `c`; or `all`).

**Secrets** are generated once by step 1 into `secrets/` (gitignored, mode 0600) and never printed:

| Secret | Form |
| --- | --- |
| AP SSID | `ap` + 6 random hex digits. Hidden, not the project name. |
| AP passphrase | 128 random bits as 32 hex characters, WPA2-PSK. |
| MQTT passwords | Independent random password per account: `frigate`, `controller`, `cam_a`, `cam_b`, `cam_c`. |
| Stream tokens | Random per camera, checked by the camera's `/stream`. |
| Channel, interface, BSSID | Detected: quietest of 1/6/11, the AP-capable Wi-Fi device, and the AP's MAC (pinned in camera firmware). |

Back up `secrets/`: losing it means reflashing every camera. Re-running an installer keeps
existing secrets. `scripts/secrets-sync.sh` moves the camera secrets between machines over SSH.

**What a flash does.** `scripts/install-esp32.sh` builds `firmware/sentinel`, writes the camera's
bind data (static IP, SSID, passphrase, BSSID, channel, MQTT login, stream token) into an
encrypted NVS image with a per-camera key, and flashes bootloader, app, NVS and key in one
esptool call. The board reboots already **BOUND**: it joins the hidden AP and streams. There is
no BLE step and no PoP to copy. BLE provisioning (`sentinel-provision bind`) still works for a
board flashed without secrets.

| Machine | Script | Installs |
| --- | --- | --- |
| Arch dev box (build + flash) | `scripts/install-arch.sh` | ESP-IDF build prerequisites, `uucp` serial access, ESP-IDF v6.0.3 + esp32s3 toolchain, repo `.venv`, esp_prov, vendored docs, bench tools (ffplay, mosquitto clients, bluez) |
| Fedora host (cubicle) | `scripts/install-fedora.sh` | Everything in step 1, plus podman/Quadlet, firewalld, BlueZ, chrony, Intel iGPU diagnostics, repo `.venv`, esp_prov, readiness checks. `--no-deploy` stops after packages and checks. |

Building firmware in a new shell: `. scripts/idf-env.sh`.
Docs only: `./scripts/fetch-docs.sh`.

Per-user paths: ESP-IDF in `~/esp/esp-idf-<ref>` with toolchains in `~/.espressif`;
esp_prov in `~/.local/share/jack-sentinel/`; recorded paths in
`~/.config/jack-sentinel/env.sh`.
