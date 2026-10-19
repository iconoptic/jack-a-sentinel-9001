# sentinel-recorder

Simple motion mode for the Sentinel cameras. One process per host pulls each
camera's `/stream` (or polls `/snapshot`), compares downscaled greyscale frames,
and writes the camera's original JPEG bytes to disk while there is motion inside
the schedule.

This package does not use ffmpeg, cv2, or numpy. Pillow decodes a small
greyscale copy for motion only. Saved frames are the bytes the camera sent.

Frigate mode is a separate install path. This service does not talk to Frigate
or MQTT.

## Run

```bash
sentinel-recorder [CONFIG]
```

No subcommand runs until SIGTERM or SIGINT. The config path is the argument,
otherwise `SENTINEL_RECORDER_CONFIG`, otherwise `/etc/sentinel/recorder.toml`.

Each `[[cameras]]` entry needs `SENTINEL_STREAM_TOKEN_<ID>` in the environment
(`SENTINEL_STREAM_TOKEN_A` for `id = "a"`). The token is sent as
`Authorization: Bearer …`. It is never put in the URL and never logged.

The process exits non-zero when a camera worker fails, so `systemctl status` shows it.

## Schedule

Recording is allowed at all times except the quiet window: `quiet_days` from
`quiet_start` (inclusive) to `quiet_end` (exclusive), in `timezone`. The shipped
defaults are Monday–Friday 06:00–16:00, so nights and weekends record.

`schedule.enabled = false` records on motion at any time (bench test).

An event that is already open when the quiet window starts finishes normally.
The schedule is checked only when an event opens.

```bash
sentinel-recorder check-schedule [CONFIG] [--at 2026-10-19T05:30]
```

Prints `allowed` (exit 0) or `quiet` (exit 1). `--at` without a UTC offset is
read in the config timezone.

## Config

`config.toml`:

| Key | Default | Meaning |
| --- | --- | --- |
| `recorder.recordings_dir` | `/var/lib/sentinel/recordings` | Event root |
| `recorder.source` | `stream` | `stream` = `GET /stream`; `snapshot` = poll `GET /snapshot` |
| `recorder.snapshot_fps` | `5` | Poll rate when `source = "snapshot"` |
| `recorder.pre_roll_seconds` | `5` | Frames kept before motion, by timestamp |
| `recorder.post_roll_seconds` | `30` | Keep writing this long after the last motion frame |
| `recorder.max_event_seconds` | `900` | Split a longer event; do not stop it |
| `recorder.latest_jpeg_seconds` | `2` | Rewrite `<camera>/latest.jpg` this often; `0` turns it off |
| `recorder.retain_days` | `30` | Delete events whose start is older than this |
| `recorder.max_disk_gb` | `100` | Then delete the oldest closed events until under this size |
| `recorder.connect_timeout_seconds` | `5` | TCP connect timeout |
| `recorder.read_timeout_seconds` | `10` | Read timeout; also the cap on how long a stalled stream waits |
| `schedule.enabled` | `true` | `false` = ignore the quiet window |
| `schedule.timezone` | `UTC` | IANA zone for the quiet window and directory names |
| `schedule.quiet_days` | weekdays | `mon` … `sun` |
| `schedule.quiet_start` | `06:00` | Inclusive, `HH:MM` |
| `schedule.quiet_end` | `16:00` | Exclusive, `HH:MM` |
| `motion.analysis_width` | `160` | Comparison width. Height keeps the frame's aspect |
| `motion.pixel_threshold` | `25` | Grey-level change that counts as a changed pixel |
| `motion.min_area_percent` | `1.0` | Share of unmasked pixels that must change |
| `motion.trigger_frames` | `2` | Consecutive motion frames required to open an event |
| `motion.background_alpha` | `0.05` | Running-average update per frame |
| `motion.masks` | `[]` | Ignore rectangles as frame fractions `[x0, y0, x1, y1]` |
| `cameras` | one `sentinel_a` | `frigate_name`, `id`, `static_ip` |

## On-disk layout

```text
/var/lib/sentinel/recordings/
  sentinel_a/
    latest.jpg
    2026-10-19/
      17-42-08/
        event.json
        frames/000001_1792449728123.jpg
        SHA256SUMS
```

Directory names are the event start in the config timezone. A second event in
the same second is `17-42-08-2`. `event.json` times are UTC with milliseconds
and a `Z`. `end_reason` is `no_motion`, `max_length`, `camera_offline`,
`shutdown`, or `recorder_restart` (an event left open by a crash, finalized on
the next start).

`SHA256SUMS` is `sha256sum -c` format, paths relative to the event directory.
`latest.jpg` is replaced by writing a temp file in the same directory and
renaming it.

View an event by opening `frames/` in any image viewer, or:

```bash
mpv "mf://frames/*.jpg" --mf-fps=5
```

## Development

```bash
cd host/recorder
python -m venv .venv
. .venv/bin/activate
pip install -e '.[dev]'
pytest -q
```

## Container

```bash
podman build -t localhost/sentinel-recorder:latest -f Containerfile .
podman run --rm localhost/sentinel-recorder:latest \
  check-schedule /etc/sentinel/recorder.toml --at 2026-10-19T17:00
```

The image is `python:3.12-slim-bookworm` and runs as uid 1000 (`sentinel`).
`tzdata` is installed so IANA zones resolve. The process does not set `TZ`;
the schedule timezone lives in the config.
