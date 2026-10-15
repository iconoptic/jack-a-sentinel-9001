# Phase 2: Host MVP (Fedora)

**Kind:** coding agent prompt (repo files + runbook)  
**Model:** Composer 2.5 Fast (`composer-2.5-fast`)  
**Wave:** A (parallel with Phase 1 and Phase 4 controller)  
**Parent plan:** [../PLAN.md](../PLAN.md#phase-2-host-mvp-fedora)

## Agent instructions

You are implementing Phase 2 **repository content and a Fedora runbook** only.
Read [CONTRACTS.md](CONTRACTS.md) first. Obey Frigate **0.18.1** keys in
`docs/vendor/frigate/` (especially `record.md`, `face_recognition.md`,
`object_detectors.md`, `go2rtc.md`, `mqtt.md`). Do not invent config keys.

This Arch machine **cannot** prove the AP, VAAPI, OpenVINO, or person detection.
Do not claim those exits. Write files a human (or later agent on Fedora) can apply.

## Goal

Scaffold the host layout so the Fedora box can run a hidden camera AP, mosquitto,
and Frigate with go2rtc ingesting one bench camera, person detection, and a
rolling record buffer with 10 s alert pre-capture.

## Already decided

- Ethernet is the host uplink. Built-in Intel Wi-Fi is the **camera AP only**.
- AP: `10.77.0.1/24`, hidden SSID, `ipv4.method manual`, `never-default`, no DHCP,
  no NAT, no forwarding. Cameras use static IPs from CONTRACTS.md.
- firewalld zone `sentinel`, target `DROP`; allow MQTT 1883 from the AP interface.
- Frigate image: `ghcr.io/blakeblackshear/frigate:0.18.1`, pin by **digest** in the
  runbook (record the digest when pulled on Fedora).
- Mosquitto: `eclipse-mosquitto:2`, also pin by digest on Fedora.
- Detector: OpenVINO on Intel iGPU (`/dev/dri`); VAAPI for MJPEG→H.264.
- `motion.mqtt_off_delay: 5` (see CONTRACTS.md).
- `record.continuous.days: 1`; alerts `pre_capture: 10`, `post_capture: 30`,
  `retain.mode: all` for alerts as in the plan sketch—validate against vendored
  `record.md`.
- `review.alerts.labels` includes `person` and `sentinel_sync`.
- Face recognition enabled, `model_size: small`; enroll-only-yourself policy stays
  a human/config note, not biometric enrollment in this phase.
- Secrets (PSK, MQTT passwords, stream tokens) under `secrets/`, never committed.
  Config may use env-file placeholders.

## Files to create

```text
host/
  README.md                    update: point at this brief + how to deploy on Fedora
  network/
    README.md                  apply order, nmcli/firewalld notes
    setup-ap.sh                idempotent-ish setup from secrets + env
    sentinel-zone.xml          or firewall-cmd scripted rules documented in README
  mosquitto/
    mosquitto.conf
    acl.example                committed example; real acl generated later / secrets
    README.md
  frigate/
    config.yml                 one camera (sentinel_a) wired per CONTRACTS
    README.md
  quadlet/
    mosquitto.container
    frigate.container
    *.volume as needed
    README.md                  install path under /etc/containers/systemd/, reboot notes
  scripts/
    probe-host.sh              lscpu, lspci wifi, iw list AP modes, ls /dev/dri, ip route
```

Password files and real tokens: document generation into `secrets/`; ship examples
only (e.g. `passwords.example`).

## Frigate / go2rtc sketch to follow

Align with CONTRACTS.md and the plan's sketch in PLAN.md §4. Minimum:

- MQTT user for Frigate (password from env/secrets).
- go2rtc stream `sentinel_a` →
  `ffmpeg:http://10.77.0.11/stream?token=...#video=h264#hardware`
  (token via env substitution if Frigate supports it in this version; otherwise
  document a generate-config step that writes the token from secrets—check vendored
  docs, do not invent unsupported templating).
- Camera `sentinel_a` with detect + record roles from the restream.
- `detect.fps: 5`, `objects.track: [person]`.
- OpenVINO detector config per vendored `object_detectors.md`.

## Runbook sections the agent must write (in host README or `host/RUNBOOK.md`)

1. Run `probe-host.sh`; paste results. OpenVINO iGPU needs Intel 6th gen or newer;
   `iw list` must show `AP` and a valid interface combination with the station/AP
   setup you use.
2. Turn off autoconnect on any saved Wi-Fi **client** profiles.
3. Apply `network/setup-ap.sh`; verify with a phone (static IP, PSK): reaches MQTT
   only; no corporate/internet; Ethernet remains default route.
4. `podman pull` Frigate and Mosquitto; record digests into the Quadlet units or a
   `digests.txt` under `secrets/` / host local override.
5. Install Quadlet units; confirm `systemctl status` / `journalctl -u frigate`.
6. Point Frigate at the Phase 1 bench camera (same LAN or temporary static IP on the
   AP as `10.77.0.11`).
7. Human exit check: walk in front of the camera → alert with ~10 s pre-roll;
   System page inference under ~20 ms.

## Out of scope

- `sentinel-controller` and `sentinel-provision` (Phase 4)
- Binding BLE cameras; Phase 1 hardcoded Wi-Fi is enough for MVP ingest
- Flash encryption, OTA, MQTT TLS
- Claiming AP/VAAPI success from the Arch agent environment

## Grok escalation (human triggers, not this agent)

If `probe-host.sh` shows **no AP mode** or CPU **older than 6th gen**, stop applying
the default runbook and run the host-probe Grok escalation in [README.md](README.md).
Fallbacks named in PLAN.md: USB UVC path, or CPU detector.

## Verify (agent)

1. YAML / unit files are syntactically consistent and match vendored Frigate 0.18.1
   keys (read the vendor docs; fix keys if the plan sketch drifts).
2. `probe-host.sh` is runnable with bash `-n` / shellcheck-clean if shellcheck exists.
3. No secrets committed.
4. State clearly in the PR/summary: Fedora exit checks remain for the human.

## Exit (phase done)

Human on Fedora: walk in front of the bench camera and get an alert with 10 s of
pre-roll. Agent exit: repo files + runbook ready.

## Stop conditions

- Stop if a required Frigate 0.18.1 key in the plan sketch is removed or renamed in
  vendored docs: adapt to the vendored docs and note the drift in the host README.
- Do not SSH into the Fedora box unless the user provides access in this chat.
