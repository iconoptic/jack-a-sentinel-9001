# Implementation plan

## Goal

Capture clear, timestamped, tamper-resistant footage of anyone who messes with
the cubicle, without keeping hours of empty-desk video.

## Requirements, as given

1. After flashing, each camera starts in a Bluetooth pairing mode and accepts exactly
   one host. Once it is bound, it stops accepting new devices.
2. After pairing, the cameras connect to an always-on Fedora box in the cubicle.
3. A service on the Fedora box handles data from all three cameras.
4. The host runs face detection on the streams. A face on **any** camera makes
   **all** cameras record, for a preset time or for as long as movement continues.

## Changes to the original idea, and why

| Original idea | Change | Why |
| --- | --- | --- |
| Pair over Bluetooth and stream over it | **Use BLE only for provisioning and binding, then stream over Wi-Fi** | The ESP32-S3 has BLE only, no Classic BT. Three cameras sharing the host's one BLE radio get about 1 frame/s each at VGA, against 10–15 fps at HD over Wi-Fi. See [the numbers](#bluetooth-or-wi-fi-for-video). Requirement 1 stays: BLE pairing mode at first boot, one host binds, then BLE is shut off permanently. |
| Face detection as the trigger | **Trigger on `person` detection. Face detection and recognition only add a label.** | Someone bent over the desk with their back to the camera produces no face, and that is exactly the footage you need. Frigate also requires a `person` detection before it runs face detection. Face-only triggering stays available as a config switch. |
| The host tells the devices to start recording | **The host records all cameras continuously into a short rolling buffer and keeps what surrounds a trigger. The trigger also tells all cameras to raise frame rate and quality.** | If the devices only start recording when triggered, you lose the moment the person walked up. A rolling buffer gives you pre-roll (e.g. 10 s before the trigger). The "all devices react" part still happens, as a mode switch on each camera plus an alert pinned on every camera in Frigate. |
| Write the monitoring service from scratch | **Use [Frigate](https://frigate.video) for ingest, detection, recording and retention, plus a small custom controller** | Frigate is the de facto open-source NVR. It is mature and already does person detection, face recognition, pre/post capture, motion-based retention and a review UI. The custom code is limited to what is specific to this project. |

## Architecture

```text
 ┌─────────── camera (×3) ───────────┐            ┌──────────────── Fedora host ────────────────────┐
 │ ESP-IDF v6.0.x firmware            │            │ Podman + Quadlet (systemd-managed containers)   │
 │                                    │   BLE      │                                                 │
 │ provisioning state machine ◄──────┼────────────┼── sentinel-provision (CLI, built on esp_prov)    │
 │   (first boot only)                │            │                                                 │
 │                                    │  Wi-Fi     │                                                 │
 │ esp32-camera (OV3660, JPEG)        │  private   │                                                 │
 │ HTTP  GET /stream  (MJPEG, token) ─┼──AP──────► │ go2rtc ─► h264 (VAAPI) ─► Frigate               │
 │       GET /snapshot                │            │             detect: person → face (+ recognize)  │
 │ MQTT  sentinel/<id>/state  (LWT)  ─┼──────────► │ mosquitto   record: rolling buffer + alerts      │
 │       sentinel/<id>/telemetry      │            │     ▲  │                                         │
 │       sentinel/<id>/cmd  ◄─────────┼────────────┼─────┘  ▼                                         │
 │ watchdog, Wi-Fi backoff, BOOT-hold │            │ sentinel-controller (Python)                    │
 │ factory reset                      │            │   - cross-camera trigger sessions               │
 └────────────────────────────────────┘            │   - camera mode commands (idle/armed)           │
                                                   │   - offline/tamper events → review timeline     │
                                                   │   - evidence export + SHA-256 manifest          │
                                                   └─────────────────────────────────────────────────┘
```

### Pinned upstream versions

| Component | Version | Role |
| --- | --- | --- |
| ESP-IDF | v6.0.3 (v6.1 just shipped; move to it once the component ecosystem catches up) | Firmware SDK |
| espressif/esp32-camera | 2.1.8 | OV3660 driver, JPEG frame buffers |
| espressif/network_provisioning | 1.3.x | BLE provisioning, Security 2, custom endpoints |
| esp-mqtt (bundled with IDF) | — | Telemetry and commands |
| Frigate | 0.18.1 | NVR: detection, face recognition, recording, review UI, API |
| go2rtc | bundled with Frigate | MJPEG → H.264 restream |
| Eclipse Mosquitto | 2.x | MQTT broker |

Docs for all of these are in `docs/vendor/`. See [README.md](README.md).

## Key designs

### 1. Pairing and lock-in ("first host wins")

The firmware state is stored in an encrypted NVS namespace `bind`:

```text
UNBOUND ──(BLE provisioning OK + bind endpoint OK)──► BOUND ──(BOOT held 10 s at power-up)──► UNBOUND
```

- **UNBOUND** (fresh flash, or after a factory reset): the camera advertises over BLE as
  `SENTINEL-xxxx` using `network_provisioning` with **Security 2 (SRP6a)**. The
  SRP verifier comes from a per-device proof-of-possession code that is generated at
  flash time and printed on the serial console. Write it on masking tape on the
  board. Without the code, a nearby phone cannot complete the session. The camera does
  not stream and does not join Wi-Fi.
- The host-side `sentinel-provision` tool, built on `esp_prov`, sends:
  1. the Wi-Fi SSID and PSK of the host's private AP (standard endpoint), then
  2. a `sentinel-bind` **custom endpoint** payload: host ID, MQTT username and password,
     stream bearer token, broker address, and the host's CA certificate if TLS is used.
- When both succeed, the camera writes `bound=1` and the secrets to encrypted NVS. It
  then calls `network_prov_mgr_deinit()` and releases BT controller memory, which returns
  about 30–60 KB of RAM to the camera pipeline.
- **BOUND**: BLE is never started again. The camera doesn't advertise and can't be
  discovered over BLE. To re-pair, you need physical access: hold BOOT for 10 s during
  power-up. The camera publishes a `factory_reset` event to MQTT before wiping, if it
  can still reach the broker.
- Hardening comes later (Phase 6). Re-flashing over USB is always possible on a stock
  board. Flash encryption plus Secure Boot v2 prevents silently re-flashing or reading
  the secrets back, but it **burns eFuses and is irreversible**. Do it on one board in
  development mode first.

### 2. Network

The ESP32-S3 is **2.4 GHz only**.

#### Bluetooth or Wi-Fi for video

BLE doesn't drop data. The link layer retransmits until each packet arrives. What you
give up is **frames and resolution**. A BLE link from the ESP32-S3 peaks around
1.3 Mbit/s under ideal conditions (2M PHY, max MTU, one connection). The host has a
single Intel combo radio that time-slices three connections and shares its antenna with
Wi-Fi, so plan on **~250–400 kbit/s per camera (~40 KB/s)**.

The table assumes 300 kbit/s per camera on BLE. Frame sizes are typical OV3660 JPEG at
quality ~12; Phase 1 will measure the real ones.

| Resolution | Typical JPEG frame | BLE, per camera | Wi-Fi 2.4 GHz, per camera |
| --- | --- | --- | --- |
| QVGA 320×240 | ~8 KB | ~4–5 fps | limited by sensor (~25+ fps) |
| VGA 640×480 | ~25 KB | **~1.5 fps** | ~20 fps |
| SVGA 800×600 | ~40 KB | ~1 fps | ~15–20 fps |
| HD 1280×720 | ~70 KB | ~0.5 fps | **~10–15 fps** |

Detail on faces matters too. With the OV3660's ~66° lens, a face 2.5 m away is about
**16 px wide at QVGA, 31 px at VGA and 63 px at HD**. Frigate's face recognition needs
roughly 40+ px to be useful. To get a usable frame rate over BLE you'd have to drop to
QVGA, and then faces are too small to recognize. Wi-Fi at HD gives both a usable frame
rate and enough face detail.

#### Recommended setup

- **Decided:** **Ethernet is the host's uplink.** The **built-in Intel Wi-Fi is
  dedicated to the camera network**, a hidden-SSID access point. It no longer joins any
  Wi-Fi as a client, so turn autoconnect off on any saved Wi-Fi profiles. No extra
  hardware is needed. The NetworkManager connection (lives in `host/network/`):
  - `802-11-wireless.mode ap`, `wifi.hidden yes`, `band bg`, a fixed channel (1, 6 or
    11, whichever is quietest in the office scan)
  - `ipv4.method manual` with address `10.77.0.1/24`, `ipv4.never-default yes` and
    `ipv6.method disabled`. **Not `shared`**: shared mode sets up NAT to the uplink and
    a DHCP server, and neither is wanted here.
  - The cameras get **static IPs** (`10.77.0.11`–`.13`) in the bind payload, so no
    DHCP server runs on the AP.
  - firewalld: the AP interface goes in its own `sentinel` zone with target `DROP`. It
    allows only MQTT from the cameras (1883, or 8883 once TLS is on) and later the OTA
    HTTPS port. Video needs no inbound port because the host pulls each stream from the
    camera. No forwarding between this zone and the Ethernet zone.

  The cameras can reach only the host, and nothing on the corporate network can reach
  the cameras.
- **What a hidden SSID does and doesn't do:** the network won't show up in a coworker's
  phone Wi-Fi list, and that is the realistic threat here, so do it. It isn't security:
  the SSID still goes over the air whenever a camera connects, and any Wi-Fi scanner
  (including corporate wireless intrusion detection) still sees a hidden network
  beaconing. Real protection comes from a long random PSK (WPA3-SAE if the Intel card
  and NetworkManager accept it in AP mode, WPA2-PSK otherwise), a MAC allowlist on the
  host firewall, and the per-device stream and MQTT credentials from binding. Give it a
  boring SSID, not `SENTINEL`.
- **ESP side:** connecting to a hidden AP needs the SSID set explicitly; it comes from the
  bind payload. Also pin the BSSID and channel in `wifi_config_t` so the camera never
  scans or broadcasts probes for anything else.
- **Fallback, wired with no RF:** the ESP32-S3's native USB can act as a UVC webcam
  (Espressif `esp-iot-solution` `usb_device_uvc`). Frigate reads `/dev/videoN`
  directly. This is the most robust option and invisible on the network. Placement is
  limited by USB cable length (about 5 m).
- **Not recommended:** joining the corporate Wi-Fi. It's usually WPA2-Enterprise with
  client isolation, it may break IT policy, and it exposes the streams.

### 3. Camera firmware behavior

- **Stream:** `GET /stream` returns `multipart/x-mixed-replace` MJPEG, and `GET /snapshot`
  returns a single JPEG. Both require the bind token, sent either as
  `Authorization: Bearer <token>` or as `?token=` (the query form is simplest for
  go2rtc and acceptable on the isolated AP). Frigate/go2rtc
  pulls the stream. One stream client at a time; go2rtc fans it out.
- **Modes** (set over MQTT `sentinel/<id>/cmd`):
  - `idle`: fixed resolution (start with **SVGA 800×600** or **HD 1280×720**; Phase 1
    decides), about 5 fps, JPEG quality ~15. This is enough for person detection.
  - `armed`: **same resolution**, higher fps (as high as the link allows, target 10–15),
    better JPEG quality (~10).
  - Resolution stays fixed on purpose. A mid-stream resolution change forces
    go2rtc/ffmpeg to renegotiate and can drop the recording segment exactly when it
    matters.
  - `armed` automatically falls back to `idle` after N seconds without a refresh, so a
    host crash can't leave cameras running hot.
- **Telemetry** every 30 s on `sentinel/<id>/telemetry`: uptime, RSSI, free heap/PSRAM,
  chip temperature, fps, dropped frames, reset reason.
- **LWT:** `sentinel/<id>/state` = `offline` (retained). It is published as `online`
  on connect. Unplugging or covering a camera shows up within seconds.
- **Robustness:** task watchdog, Wi-Fi reconnect with exponential backoff, a reboot
  if the camera driver errors N times in a row, brownout detector on.
- **Later:** OTA over HTTPS from the host, so mounted cameras never need a USB cable.

### 4. Host services (Fedora, Podman Quadlet)

Each service is a `.container` Quadlet unit, so systemd handles start-at-boot, restarts
and logs (`journalctl -u frigate`):

| Unit | Image | Notes |
| --- | --- | --- |
| `mosquitto.container` | `eclipse-mosquitto:2` | Per-camera credentials and ACLs: each camera can publish only `sentinel/<own id>/#` and read only its own `cmd`. The controller and Frigate have their own users. |
| `frigate.container` | `ghcr.io/blakeblackshear/frigate:0.18.1` (pinned) | `/dev/dri` for VAAPI/OpenVINO, `--shm-size` per docs, recordings on a dedicated volume, SELinux `:Z` labels. |
| `sentinel-controller.container` | built from `host/controller/` | Python, `paho-mqtt` + `httpx`. Talks to Frigate over MQTT and HTTP. |

**Frigate config sketch** (the real version goes in `host/frigate/config.yml`):

```yaml
mqtt:
  host: 127.0.0.1
  user: frigate
  password: "{FRIGATE_MQTT_PASSWORD}"

go2rtc:
  streams:
    sentinel_a: "ffmpeg:http://10.77.0.11/stream?token={TOKEN_A}#video=h264#hardware"
    # sentinel_b, sentinel_c ...

cameras:
  sentinel_a:
    ffmpeg:
      inputs:
        - path: rtsp://127.0.0.1:8554/sentinel_a
          roles: [detect, record]
    detect:
      fps: 5
    objects:
      track: [person]

record:
  enabled: true
  continuous:
    days: 1            # rolling buffer: this is what makes pre-roll and cross-camera saves possible
  motion:
    days: 7
  alerts:
    pre_capture: 10
    post_capture: 30
    retain:
      days: 90
      mode: all

face_recognition:
  enabled: true
  model_size: small    # try 'large' on the Intel iGPU via OpenVINO once detection is stable

review:
  alerts:
    labels: [person, sentinel_sync]
```

The `record` and `face_recognition` keys have been checked against the vendored 0.18.1
docs. The rest is a sketch of intent, not tested config. Check it against
`docs/vendor/frigate/` and `docs/vendor/go2rtc/` while implementing.

### 5. Cross-camera trigger: `sentinel-controller`

This is the custom part, and it is small and testable:

```text
IDLE ──(frigate/reviews: new alert, severity=alert, label∈trigger_labels, on any camera)──► ARMED
ARMED:
  - publish sentinel/+/cmd {"mode":"armed","ttl":60} to all cameras (re-sent every 20 s)
  - POST /api/events/<cam>/sentinel_sync/create {"duration": null}
    for each *other* camera, so all three cameras' footage is kept as an alert
  - track frigate/<cam>/motion ON/OFF across all cameras
ARMED ──(no motion on any camera for hold_seconds, or max_session reached)──► COOLDOWN
COOLDOWN:
  - PUT /api/events/<id>/end for each sentinel_sync event
  - publish {"mode":"idle"}; export evidence
  - a new alert during COOLDOWN re-arms immediately (no dead window)
```

Config (`host/controller/config.toml`):

| Key | Default | Meaning |
| --- | --- | --- |
| `trigger_labels` | `["person"]` | Set to `["face"]` for strict face-only triggering |
| `hold_seconds` | `60` | Keep recording this long after the last motion on any camera |
| `max_session_seconds` | `900` | Hard cap, so a stuck motion sensor can't record forever |
| `ignore_sub_labels` | `[]` | For example `["me"]` to skip triggers when Frigate recognizes you. See the note on faces below. |
| `notify` | off | Optional hook (ntfy/email) if push alerts are ever wanted. Not planned for now. |

**Other controller jobs:**

- **Tamper and offline events:** when a camera's LWT goes `offline` or Frigate reports
  no frames, that is logged as a `camera_offline` review item. Covering or unplugging a
  camera is itself evidence, so the controller also triggers a save on the remaining
  cameras. No push notifications for now; it all appears in the Frigate review
  timeline.
- **Evidence export:** when a session ends, it pulls the clips and snapshots for every
  camera in the session window from the Frigate API into
  `evidence/<UTC timestamp>/` on the host and writes `manifest.json` with SHA-256
  hashes and the host clock source. These exports are kept outside Frigate's retention,
  so they don't age out. No off-box copy (decided: the host is company property and
  isn't considered at risk).
- **Health:** daily summary with uptime per camera, disk usage and alert count.

### 6. Faces: detection vs. recognition

- **Face detection** (is there a face in this frame) is all the trigger needs. It
  stores nothing about who anyone is.
- **Face recognition** (whose face is this) needs a library of enrolled faces. In many
  places (Illinois BIPA, Texas, Washington, the EU/UK GDPR) collecting other people's
  face templates without consent is regulated biometric processing. **Default plan:
  enroll only yourself**, so the system can skip triggers caused by you
  (`ignore_sub_labels`). Leave coworkers unenrolled. The clips identify them well
  enough for a human to recognize.

## Phases

Each phase ends with something working that you can check.

**Implementer briefs** (fresh-agent prompts, models, parallelism): see
[phases/README.md](phases/README.md). Frozen wire formats live in
[phases/CONTRACTS.md](phases/CONTRACTS.md). This section stays the checklist and
exit criteria; the briefs tell an agent what to build.

### Phase 0: Ground rules (before mounting anything)

- [x] Workplace sign-off: confirmed OK (2026-10-14).
- [ ] **Video only, no audio.** Audio recording brings in wiretap and consent laws in
      many US states. The OV3660 boards have no mic, so keep it that way.
- [ ] Aim the cameras at your own space, not at neighbors' desks or walkways.
- [ ] Consider a visible "this desk is on camera" sign. Deterrence may fix the problem
      before you need evidence.

### Phase 1: Bench bring-up (one board)

- [ ] Install ESP-IDF v6.0.3 on the dev machine (`docs/vendor/esp-idf/docs/en/get-started/`).
- [ ] Identify the ports, chip, flash, PSRAM and sensor. Fill in the checklist in
      [hardware.md](hardware.md).
- [ ] Build the `esp32-camera` example with the ESP32-S3-EYE pinout and Octal PSRAM
      (`CONFIG_SPIRAM_MODE_OCT=y`), hardcoded Wi-Fi, and a basic MJPEG endpoint.
- [ ] Measure fps at VGA, SVGA, HD and UXGA, plus temperature after 30 min. **Choose the
      fixed stream resolution.**

**Exit:** one camera streams stably for 24 h on the bench.

### Phase 2: Host MVP (Fedora)

- [ ] Record exact host details: `lscpu | grep 'Model name'` (OpenVINO GPU needs Intel
      6th gen or newer), `lspci -k | grep -A3 -i network`, `iw list` (look for `AP`
      under "Supported interface modes" and for valid interface combinations),
      `ls /dev/dri`.
- [ ] Set up the hidden-SSID AP on the built-in Wi-Fi as described in
      [Network](#2-network), scripted in `host/network/`. Test it:
  - A phone with the PSK and a static IP can join.
  - The phone can reach only the host's MQTT port.
  - The phone cannot reach the corporate network or the internet.
  - Ethernet stays the default route (`ip route`).
- [ ] Add Quadlet units for mosquitto and Frigate, with `podman` pulls pinned by digest.
- [ ] Frigate ingests the Phase 1 camera through go2rtc, detects `person`, and keeps a
      rolling recording buffer.
- [ ] Detector: OpenVINO on the Intel iGPU (`/dev/dri` passed into the container), with
      VAAPI for the MJPEG→H.264 transcode. Check inference time in Frigate's System
      page; target under 20 ms.

**Exit:** you walk in front of the bench camera and get an alert with 10 s of pre-roll.

### Phase 3: Sentinel firmware v1

- [ ] ESP-IDF project in `firmware/sentinel/` with `idf_component.yml` pinning
      esp32-camera and network_provisioning, and a committed `dependencies.lock`.
- [ ] Bind state machine, BLE Security 2 provisioning, `sentinel-bind` custom endpoint,
      encrypted NVS.
- [ ] Authenticated `/stream` and `/snapshot`.
- [ ] MQTT telemetry, LWT, idle/armed mode with TTL.
- [ ] Watchdog, Wi-Fi backoff, BOOT-hold factory reset.
- [ ] Unit tests for the bind state machine and command parsing, with ESP-IDF's
      Linux-target host tests where possible.

**Exit:** a freshly flashed board appears over BLE. After binding it streams. After a
reboot it never advertises again. A BOOT-hold reset returns it to UNBOUND.

### Phase 4: Provisioning tool and controller

- [ ] `host/provision/`: a `sentinel-provision` CLI that wraps `esp_prov` over BLE. It
      generates per-camera MQTT creds and a stream token, writes the mosquitto ACL
      entry, the go2rtc stream and the Frigate camera block, then sends the bind payload.
      One command per camera.
- [ ] `host/controller/`: the state machine above, with pytest tests driven by recorded
      `frigate/reviews` payloads.
- [ ] Quadlet unit for the controller.

**Exit:** all three cameras are bound. Triggering one camera produces saved, exported
alerts on all three, and the cameras switch to armed and back.

### Phase 5: Deploy in the cubicle

- [ ] Mount the cameras: angles that cover the desk surface and the approach, with
      overlapping fields of view so one covered camera doesn't blind the system.
- [ ] Build the power harness ([hardware.md § Power](hardware.md#power)): one 5 V
      supply, a trunk of 18–20 AWG wire, a bulk capacitor at each camera. Run it out of
      reach, with tidy, tamper-evident placement.
- [ ] Draw Frigate motion masks over monitors and windows to avoid false motion.
- [ ] Run for one week, then tune `hold_seconds`, detection thresholds and retention.

### Phase 6: Hardening

- [ ] OTA updates from the host, with signed images.
- [ ] Flash encryption and Secure Boot v2: development mode on one board, then release
      mode. **Irreversible.**
- [ ] MQTT over TLS with a host CA (the CA certificate is delivered in the bind payload).
- [ ] Fedora host: LUKS on the recordings disk, auto-login disabled.

## Planned repo layout

```text
firmware/
  sentinel/            ESP-IDF project (main/, components/, sdkconfig.defaults, partitions.csv)
host/
  frigate/config.yml
  mosquitto/           mosquitto.conf, acl (passwords generated, gitignored)
  controller/          Python package + tests + Containerfile
  provision/           sentinel-provision CLI
  quadlet/             *.container, *.volume, *.network units
  network/             hotspot setup script
scripts/
  fetch-docs.sh
docs/
```

## Open questions for you

1. ~~**Fedora box hardware**~~ Answered: i7, Intel graphics, >500 GB, built-in Wi-Fi and
   BT, with **Ethernet as the uplink**, so the built-in Wi-Fi becomes the camera AP. Still
   useful: the exact i7 generation (`lscpu | grep 'Model name'`). OpenVINO on the iGPU
   needs 6th gen or newer.
2. ~~Placement and power~~ Power is available. The plan is one 5 V supply plus a custom
   three-drop harness; see [hardware.md § Power](hardware.md#power). Wi-Fi carries the
   video, and USB carries power only.
3. ~~Off-box evidence~~ Not needed. Evidence stays on the host.
4. ~~Notifications~~ Not for now. Events go to the Frigate review timeline.
5. ~~Workplace sign-off~~ Confirmed OK.
6. **Where will you flash the boards:** this Arch dev machine or the Fedora box? ESP-IDF
   gets installed there in Phase 1.
