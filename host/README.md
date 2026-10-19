# Host (Fedora)

Files for the cubicle Fedora box: a hidden camera AP, mosquitto, and Frigate
0.18.1 with one bench camera. The procedure is [RUNBOOK.md](RUNBOOK.md). The
phase brief is [../docs/phases/02-host-mvp.md](../docs/phases/02-host-mvp.md).
Wire values are [../docs/phases/CONTRACTS.md](../docs/phases/CONTRACTS.md).

Nothing in this checkout was run on the Fedora machine. An Arch agent cannot
show that the AP, VAAPI, OpenVINO, or person detection works. Those checks are
in the runbook and stay with a person on that box.

## Layout

| Path | Role |
| --- | --- |
| [network/](network/) | Hidden AP on the built-in Wi-Fi. Ethernet stays the uplink. |
| [mosquitto/](mosquitto/) | Broker config and ACL example. Passwords are generated under `secrets/`. |
| [frigate/](frigate/config.yml) | One camera, `sentinel_a` at `10.77.0.11`. |
| [quadlet/](quadlet/) | Podman Quadlet units for `/etc/containers/systemd/`. |
| [scripts/probe-host.sh](scripts/probe-host.sh) | Print CPU, Wi-Fi AP capability, `/dev/dri`, and routes. |
| [scripts/generate-secrets.sh](scripts/generate-secrets.sh) | Create, once and idempotently: `secrets/ap.env` (random hidden SSID + passphrase), MQTT passwords for all accounts, ACL, per-camera stream tokens. |
| [network/install-ap.sh](network/install-ap.sh) | Pick interface and channel, free the radio from client profiles, run `setup-ap.sh`, record the BSSID. |
| [scripts/install-services.sh](scripts/install-services.sh) | Pull and pin images, hash MQTT passwords, install configs and Quadlet units, and start the selected mode (`--mode frigate` or `--mode simple`). |
| [scripts/pin-digests.sh](scripts/pin-digests.sh) | Pull images on Fedora and pin `Image=` by digest. `--skip-frigate` pins Mosquitto only. |
| [scripts/hash-mqtt-passwords.sh](scripts/hash-mqtt-passwords.sh) | Build the mosquitto password file with the image's `mosquitto_passwd`. |
| [scripts/render-frigate-config.sh](scripts/render-frigate-config.sh) | Manual single-token fallback. The installer instead renders all cameras and tokens with `sentinel-provision render-frigate`, so it never depends on go2rtc substituting the token. |

`secrets/` is gitignored. Examples live next to the configs (`ap.env.example`,
`passwords.example`, `acl.example`).

## Config drift from the plan sketch

Vendored Frigate 0.18.1 docs win where the sketch in `docs/PLAN.md` was incomplete.

- `detect.enabled` defaults to false in `advanced/reference.md`. The camera sets `enabled: true`.
- The OpenVINO block (detector `device: GPU`, MobileNet v2 paths, 300×300, `nhwc` / `bgr`) is the getting-started example. The sketch did not name those keys. The model files are bundled in the image (`network_requirements.md`).
- `ffmpeg.hwaccel_args: preset-vaapi` decodes the H.264 restream (`hardware_acceleration_video.md`). MJPEG to H.264 is go2rtc's `#video=h264#hardware` (`camera_specific.md`), which needs `/dev/dri`.
- The camera input uses `preset-rtsp-restream`. Record output uses `preset-record-generic` because these cameras have no audio; the default record preset expects an AAC audio track (`ffmpeg_presets.md`).
- `record.continuous.days: 1`, `motion.days: 7`, alert `pre_capture: 10`, `post_capture: 30`, `retain.days: 90`, `retain.mode: all` match the sketch and `record.md`. `mode: all` is what keeps the whole pre-roll window, not only frames where motion was detected. Segments are about 10 seconds, so the saved pre-roll can be slightly shorter or longer than 10.
- `motion.mqtt_off_delay: 5` is the `motion` key in `reference.md` (default 30).
- go2rtc API, RTSP, and WebRTC listen on `127.0.0.1` (go2rtc security notes). Frigate's UI and internal API listen on `127.0.0.1` (`networking.listen` in `reference.md`).
- `installation.md` describes port 8971 as "without TLS". `tls.md` says TLS is on by default with a self-signed certificate. Use `https://127.0.0.1:8971` and accept the certificate.
- `{FRIGATE_STREAM_TOKEN_A}` in the go2rtc URL follows `advanced/system.md`: go2rtc stream text is substituted from the container environment, not from the config `environment_vars` block. The reference config's substitution examples do not include stream URLs. If the journal shows the placeholder still in the URL, use the render script in the runbook.
- Phase 1's bring-up stream does not check the token. The query parameter stays so the URL matches `CONTRACTS.md` when Phase 3 starts enforcing it.

Face recognition is enabled with `model_size: small`. Enroll only yourself, and not in this phase. The `large` model and its `device` key stay unused until detection is already stable.

## Out of scope

MQTT TLS (Phase 6) is later. The controller and `sentinel-provision` exist; the installer deploys the controller. The ACL example leaves commented lines for cameras `b` and `c` and for a `controller` user.
