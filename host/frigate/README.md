# Frigate

`config.yml` is Frigate **0.18.1** for camera `sentinel_a` (`10.77.0.11`).
Key notes and drift from the plan sketch are in [../README.md](../README.md).
Install and the walk-through are in [../RUNBOOK.md](../RUNBOOK.md).

Copy this file to `/etc/sentinel/frigate/config.yml`. The Quadlet mounts it
over the config volume's `config.yml`, so the database and the face-model
cache stay on `frigate-config.volume` and this file stays the config.

Environment file `/etc/sentinel/frigate.env` (from `secrets/frigate.env`):

| Variable | Purpose |
| --- | --- |
| `FRIGATE_MQTT_HOST` | `127.0.0.1` |
| `FRIGATE_MQTT_USER` | `frigate` |
| `FRIGATE_MQTT_PASSWORD` | mosquitto password for that user |
| `FRIGATE_STREAM_TOKEN_A` | query token in the go2rtc MJPEG URL |

Those MQTT fields are in the reference config's substitution list. The go2rtc
stream URL is not. `advanced/system.md` says stream text is substituted from
the container environment. If the log still contains `{FRIGATE_STREAM_TOKEN_A}`,
run `host/scripts/render-frigate-config.sh --force` and do not commit the result.

UI: `https://127.0.0.1:8971`. Inference target on the System page is under
about 20 ms on the OpenVINO GPU detector. Alerts need `detect.enabled: true`
(the upstream default is false) and a person in view. Pre-roll is judged in
History, not in the trimmed Explore clip.

Face recognition uses `model_size: small`. When a person enrolls, enroll only
yourself. This phase does not upload a face.
