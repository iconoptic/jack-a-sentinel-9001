# Frozen contracts

Every coding brief in this directory points here. Implementers follow these
interfaces. Do not invent a second protocol. Architecture decisions live in
[../PLAN.md](../PLAN.md); this file freezes the wire formats and constants.

Pinned upstream versions are in [../vendor/VERSIONS.tsv](../vendor/VERSIONS.tsv)
(after `./scripts/fetch-docs.sh`). Check Frigate and go2rtc keys against
`docs/vendor/frigate/` and `docs/vendor/go2rtc/` while implementing.

## Development machines

| Role | Machine | Notes |
| --- | --- | --- |
| Firmware develop + flash | Arch Linux (this repo's usual checkout) | Install ESP-IDF v6.0.3 here. |
| Host services | Fedora box in the cubicle | Podman Quadlet, private AP, Frigate, mosquitto, controller. |

If a board is not plugged into the Arch machine, a Phase 1 agent stops after the
project builds. Live flash and stream verification are human steps on that machine.

## Camera identities

| Frigate / go2rtc name | Camera id (`<id>`) | Static IP |
| --- | --- | --- |
| `sentinel_a` | `a` | `10.77.0.11` |
| `sentinel_b` | `b` | `10.77.0.12` |
| `sentinel_c` | `c` | `10.77.0.13` |

MQTT topics use `sentinel/<id>/…` (short id). Frigate camera names use the
`sentinel_*` form above.

## Stream resolution (provisional product default)

| Mode | Resolution | Target fps | JPEG quality |
| --- | --- | --- | --- |
| `idle` | **HD 1280×720** | 5 | ~15 |
| `armed` | **same HD** (no mid-stream change) | up to 15 | ~10 |

Phase 1 still measures VGA, SVGA, HD, and UXGA. Change this default only if the
measurement sheet shows the sensor is not an OV3660, or HD cannot hold a stable
stream without thermal throttling. That change is a Grok escalation that edits
this section and names the `framesize` constant Phase 3 must use. If HD holds,
keep this table.

## Private camera network

| Item | Value |
| --- | --- |
| Host AP address | `10.77.0.1/24` |
| Uplink | Host Ethernet (default route). AP has `ipv4.never-default yes`. |
| DHCP / NAT / forwarding | None. Cameras get static IPs from the bind payload. |
| SSID | Hidden, boring name (not `SENTINEL`). Stored in secrets, not git. |
| Band / channel | 2.4 GHz (`bg`), fixed channel 1, 6, or 11 after a quiet-channel scan. |
| Firewall | firewalld zone `sentinel`, target `DROP`. Allow MQTT from cameras (1883; 8883 in Phase 6). Video is host-pull; no inbound stream port on the host for cameras. No forwarding to the Ethernet zone. |

ESP side: pin SSID, BSSID, and channel in `wifi_config_t` so the camera does not
scan or broadcast probes for anything else. Connecting to a hidden AP requires the
SSID set explicitly (it comes from provisioning + bind).

## Pairing and bind

### BLE advertising (UNBOUND only)

- Name: `SENTINEL-` plus the last two MAC bytes (four hex chars), e.g. `SENTINEL-A1B2`.
- Component: `network_provisioning` with **Security 2 (SRP6a)**.
- Proof-of-possession: generated at flash time, printed on the serial console, written
  on masking tape on the board. Never committed to git.

### Standard Wi-Fi endpoint

SSID and PSK of the host's private AP go through the **standard**
`network_provisioning` Wi-Fi credential endpoint (same as `esp_prov`).

### Custom endpoint `sentinel-bind`

JSON payload (exact field names):

```json
{
  "host_id": "fedora-cubicle-1",
  "camera_id": "a",
  "static_ip": "10.77.0.11",
  "gateway": "10.77.0.1",
  "netmask": "255.255.255.0",
  "wifi_bssid": "aa:bb:cc:dd:ee:ff",
  "wifi_channel": 6,
  "mqtt_broker": "10.77.0.1",
  "mqtt_port": 1883,
  "mqtt_username": "cam_a",
  "mqtt_password": "<generated>",
  "stream_token": "<generated>"
}
```

- Phase 3–5: no TLS. Omit any CA field.
- Phase 6+: add `"mqtt_ca_pem": "<PEM text>"` and use port `8883` when TLS is on.
  Until then, firmware must accept payloads without `mqtt_ca_pem`.

On success: write `bound=1` and secrets to encrypted NVS namespace `bind`, call
`network_prov_mgr_deinit()`, release BT controller memory. **BOUND** never starts
BLE again.

### Pre-provisioned bind (one-click flash)

`scripts/install-esp32.sh` skips BLE by writing the bind result straight into the encrypted
NVS namespace `bind`: the same keys the BLE path saves, plus optional `wifi_ssid` and
`wifi_psk` (the standard Wi-Fi endpoint's content). The bind JSON accepts the same two
optional fields, both or neither. Boards bound over BLE keep SSID/PSK in the `esp_wifi`
namespace and are unaffected.

### Factory reset

Hold **BOOT** for 10 s during power-up. Publish `factory_reset` on MQTT if the
broker is reachable, then wipe bind NVS and reboot to UNBOUND.

## HTTP (camera)

| Method | Path | Auth | Body |
| --- | --- | --- | --- |
| `GET` | `/stream` | `Authorization: Bearer <token>` **or** `?token=` | `multipart/x-mixed-replace` MJPEG |
| `GET` | `/snapshot` | same | single JPEG |

- One stream client at a time; go2rtc fans out on the host.
- Query-token form is preferred for go2rtc on the isolated AP.

go2rtc source shape (Frigate config):

```text
ffmpeg:http://10.77.0.11/stream?token={TOKEN_A}#video=h264#hardware
```

## MQTT (cameras ↔ host)

Broker: `10.77.0.1:1883` (TLS `8883` from Phase 6). Per-camera credentials; ACL:
each camera publishes only `sentinel/<own id>/#` and subscribes only to its own `cmd`.

| Topic | Direction | Retained | Payload |
| --- | --- | --- | --- |
| `sentinel/<id>/state` | camera → broker | yes | `online` on connect; LWT `offline` |
| `sentinel/<id>/telemetry` | camera → broker | no | JSON every 30 s (see below) |
| `sentinel/<id>/cmd` | host → camera | no | mode command (see below) |

### Telemetry JSON

```json
{
  "uptime_s": 12345,
  "rssi": -55,
  "heap_free": 120000,
  "psram_free": 4000000,
  "temp_c": 48.5,
  "fps": 5.1,
  "dropped_frames": 3,
  "reset_reason": "poweron",
  "mode": "idle"
}
```

### Command JSON

```json
{"mode": "idle"}
```

```json
{"mode": "armed", "ttl": 60}
```

- `armed` falls back to `idle` when `ttl` seconds pass without a refresh.
- Controller re-sends `armed` about every 20 s while a session is active.
- Unknown fields: ignore. Unknown `mode`: ignore and stay in current mode.

## Frigate trigger and cross-camera save

Pinned image: `ghcr.io/blakeblackshear/frigate:0.18.1` (pull by digest on Fedora).

### When the controller arms

Subscribe to `frigate/reviews`. Arm when:

1. `type` is `new` or `update`, and
2. `after.severity` is `alert`, and
3. `after.data.objects` intersects `trigger_labels` (default `["person"]`), and
4. `after.data.sub_labels` does **not** intersect `ignore_sub_labels` (default `[]`).

### Motion hold

Subscribe to `frigate/<camera_name>/motion` (`ON` / `OFF`). Frigate delays `OFF` by
`mqtt_off_delay` under `motion` (Frigate default 30 s). Phase 2 sets
`mqtt_off_delay: 5`. Controller `hold_seconds` starts when `OFF` arrives on **all**
cameras; do not add another 30 s on top of Frigate's delay.

### Manual sync events

For each *other* camera in the session:

```http
POST /api/events/{camera_name}/sentinel_sync/create
Content-Type: application/json

{"duration": null, "include_recording": true}
```

End with:

```http
PUT /api/events/{event_id}/end
```

Creating a manual event does **not** publish `frigate/events`. List `sentinel_sync`
under `review.alerts.labels` so the review item is an alert.

### Controller config defaults (`host/controller/config.toml`)

| Key | Default | Meaning |
| --- | --- | --- |
| `trigger_labels` | `["person"]` | Set to `["face"]` for face-only |
| `hold_seconds` | `60` | After last motion `OFF` across all cameras |
| `max_session_seconds` | `900` | Hard cap |
| `ignore_sub_labels` | `[]` | e.g. `["me"]` after self-enrollment |
| `notify` | off | Not planned for now |

### Session state machine

```text
IDLE ──(qualifying frigate/reviews on any camera)──► ARMED
ARMED:
  - publish sentinel/+/cmd {"mode":"armed","ttl":60} to all cameras (every ~20 s)
  - POST sentinel_sync create on each other camera
  - track frigate/<cam>/motion
ARMED ──(no motion on any camera for hold_seconds, or max_session)──► COOLDOWN
COOLDOWN:
  - PUT /api/events/<id>/end for each sentinel_sync event
  - publish {"mode":"idle"}; export evidence
  - a new qualifying alert during COOLDOWN re-arms immediately
```

Offline / no-frames on one camera: log `camera_offline`, trigger a save on the
remaining cameras (same armed path).

## Evidence export

Directory: `evidence/<UTC timestamp>/` on the host (gitignored). Outside Frigate
retention.

`manifest.json` must include at least:

- session start/end (UTC)
- camera names in the session
- Frigate event / review ids
- relative paths of exported clips and snapshots
- SHA-256 of each file
- host clock source note (e.g. `chrony` / system UTC)

No off-box copy.

## Secrets layout

All secrets live under `secrets/` (gitignored). Examples:

- Wi-Fi PSK, PoP codes, MQTT passwords, stream tokens
- mosquitto password file
- Phase 6 CA and signing keys

Never commit `*.env`, `*.pem`, `*.key` (except documented public test fixtures under
`docs/` if ever needed).

## Out of scope until named phases

| Item | Phase |
| --- | --- |
| OTA over HTTPS | 6 |
| MQTT TLS + CA in bind payload | 6 |
| Flash encryption / Secure Boot v2 | 6 (Grok + human; irreversible) |
| Push notifications | not planned |
| Audio | never |
