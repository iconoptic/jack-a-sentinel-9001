# Phase 7: Simple motion mode (no Frigate, no ffmpeg)

**Kind:** coding agent prompts (fresh chats)  
**Model:** Composer 2.5 Fast (`composer-2.5-fast`) for every prompt  
**Parent plan:** [../PLAN.md](../PLAN.md). Wire values: [CONTRACTS.md](CONTRACTS.md).

| Prompt | Required | Depends on | Can run with |
| --- | --- | --- | --- |
| **A — `sentinel-recorder` package** | yes | the frozen interface below | B |
| **B — installer wiring + docs** | yes | the frozen interface below (not A's code) | A |
| **C — single-camera fix for Frigate mode** | optional | nothing | A, B |
| **D — Frigate ffmpeg input fix** | optional, gated | [SYNC-DEPLOY-PC.md](SYNC-DEPLOY-PC.md) done, new firmware flashed, error text pasted | — |

Paste one prompt section per fresh chat. Do not do two prompts in one chat.

---

## Why this mode exists

Frigate mode (Phases 2–4) is: camera MJPEG → go2rtc → **ffmpeg** transcode to H.264
(VAAPI) → Frigate's ffmpeg decode/record → OpenVINO person detection → controller.
On the deployed box the ffmpeg step keeps failing with input-format errors.

Frigate cannot run without ffmpeg; every Frigate camera is an ffmpeg process. So the
way to get a mode that does not depend on ffmpeg or on a video codec is to not use
Frigate for it. **Simple mode** is one small Python service that:

1. pulls the camera's existing `/stream` (multipart JPEG, CONTRACTS.md, no firmware change),
2. detects motion by comparing downscaled greyscale frames (Pillow only, no OpenCV,
   no numpy, no ffmpeg),
3. saves the camera's own JPEG bytes untouched while there is motion, with a few seconds
   of pre-roll, but only inside the schedule.

**Schedule (the owner's words):** record on movement between 4:00 pm and 6:00 am Monday
to Friday, and any time on the weekend. Implemented as: **recording is allowed at all
times except Monday–Friday 06:00–16:00 host-local time.** (So Monday 00:00–06:00 is
covered, as the end of the weekend night.)

Frigate mode stays in the repo, unchanged, and stays the default. The two modes are
exclusive because the camera serves one stream client at a time (its HTTP server is
single-threaded; a second client just waits). The installer switches between them.

No person detection, no face recognition, no cross-camera trigger and no MQTT in this mode.
Mosquitto still runs so the camera firmware's MQTT telemetry and LWT keep working.

---

## Frozen interface (Prompts A and B both obey this; do not change it)

| Item | Value |
| --- | --- |
| Source dir | `host/recorder/` (sibling of `host/controller/`, same layout: `pyproject.toml`, `README.md`, `Containerfile`, `config.toml`, `src/sentinel_recorder/`, `tests/`) |
| Console script | `sentinel-recorder` → `sentinel_recorder.__main__:main` |
| Run | `sentinel-recorder [CONFIG]` (no subcommand = run forever) |
| Schedule check | `sentinel-recorder check-schedule [CONFIG] [--at 2026-10-19T05:30]` prints `allowed` or `quiet`, exit 0 / 1. `--at` without offset = config timezone. |
| Config path | arg, else env `SENTINEL_RECORDER_CONFIG`, else `/etc/sentinel/recorder.toml` |
| Stream token | env `SENTINEL_STREAM_TOKEN_<ID>` with `<ID>` = camera id upper-cased (`SENTINEL_STREAM_TOKEN_A`). Sent as `Authorization: Bearer <token>`, never in the URL, never logged. |
| Env file on host | `/etc/sentinel/recorder.env`, mode 0600, only the tokens for the selected cameras |
| Config on host | `/etc/sentinel/recorder.toml`, rendered by the installer, mode **0644** (no secrets; the container's uid 1000 must read it) |
| Image | `localhost/sentinel-recorder:latest`, base `docker.io/library/python:3.12-slim-bookworm`, runs as uid 1000 user `sentinel` (copy the controller Containerfile pattern) |
| Recordings in container | `/var/lib/sentinel/recordings` |
| Volume | `host/quadlet/sentinel-recordings.volume` with `VolumeName=sentinel-recordings` (host path `/var/lib/containers/storage/volumes/sentinel-recordings/_data`) |
| Unit | `host/quadlet/sentinel-recorder.container`, `Network=host`, `Restart=always` |
| Runtime deps | `httpx>=0.27`, `Pillow>=10`, `tzdata` (slim image has no zoneinfo database). Nothing else. |
| Mode marker | `/etc/sentinel/mode` contains `frigate` or `simple` |

### `config.toml` schema and defaults

```toml
[recorder]
recordings_dir = "/var/lib/sentinel/recordings"
source = "stream"              # "stream" = GET /stream; "snapshot" = poll GET /snapshot
snapshot_fps = 5               # only for source = "snapshot"
pre_roll_seconds = 5
post_roll_seconds = 30         # keep recording this long after the last motion frame
max_event_seconds = 900        # split (not stop) longer events
latest_jpeg_seconds = 2        # refresh <camera>/latest.jpg this often, for aiming; 0 = off
retain_days = 30
max_disk_gb = 100
connect_timeout_seconds = 5
read_timeout_seconds = 10

[schedule]
enabled = true                 # false = record on motion at any time (bench test)
timezone = "UTC"               # the installer writes the host's IANA zone here
quiet_days = ["mon", "tue", "wed", "thu", "fri"]
quiet_start = "06:00"          # inclusive
quiet_end = "16:00"            # exclusive

[motion]
analysis_width = 160           # frames are compared at this width (JPEG draft decode)
pixel_threshold = 25           # 0-255 grey-level change that counts as a changed pixel
min_area_percent = 1.0         # share of unmasked pixels that must change
trigger_frames = 2             # consecutive motion frames needed to start an event
background_alpha = 0.05        # running-average background update per frame
masks = []                     # ignore rectangles as frame fractions: [[x0, y0, x1, y1], ...]

[[cameras]]
frigate_name = "sentinel_a"
id = "a"
static_ip = "10.77.0.11"
```

Camera identities are CONTRACTS.md's table. The shipped `config.toml` lists only
`sentinel_a`; the installer renders the cameras chosen with `--cameras`.

### On-disk layout (one event = one directory)

```text
/var/lib/sentinel/recordings/
  sentinel_a/
    latest.jpg                              atomic write (tmp + rename), not an event
    2026-10-19/                             host-local date the event started
      17-42-08/                             host-local start time; add -2, -3 on collision
        event.json
        frames/000001_1792449728123.jpg     <seq:06d>_<UTC epoch ms>.jpg, bytes exactly as received
        frames/000002_1792449728324.jpg
        SHA256SUMS                          `sha256sum -c` format, paths relative to the event dir
```

`event.json`:

```json
{
  "camera": "sentinel_a",
  "start_utc": "2026-10-19T22:42:08.123Z",
  "end_utc": "2026-10-19T22:43:51.900Z",
  "timezone": "America/Chicago",
  "frames": 518,
  "pre_roll_frames": 25,
  "bad_frames_dropped": 0,
  "end_reason": "no_motion",
  "recorder_version": "0.1.0"
}
```

`end_reason` is one of `no_motion`, `max_length`, `camera_offline`, `shutdown`,
`recorder_restart`. Write `event.json` with `"end_utc": null` when the event opens and
rewrite it when it closes. `SHA256SUMS` is written at close.

Viewing needs no special tool: open `frames/` in any image viewer, or
`mpv "mf://frames/*.jpg" --mf-fps=5`.

---

## Prompt A — `sentinel-recorder` package

### Agent instructions

Build the Python package in `host/recorder/` exactly as the frozen interface above
says. Read `host/controller/` first and copy its conventions: hatchling `pyproject.toml`,
`src/` layout, `tomllib` config loading into dataclasses, `logging` format, Containerfile
shape, pytest settings. You are on the Arch dev box. No camera, Fedora host or container
runtime is needed for the tests. Do not touch `host/scripts/`, `host/quadlet/`,
`host/frigate/`, `host/controller/`, `firmware/` or `docs/` (Prompt B owns those).

**Do not use ffmpeg, OpenCV, numpy or any video library.** Frames are stored as the
bytes the camera sent. Pillow is used only to decode a small greyscale copy for motion.

### Modules

```text
src/sentinel_recorder/
  __init__.py      __version__ = "0.1.0"
  __main__.py      argparse: run (default) and check-schedule; one worker thread per camera; SIGTERM -> clean shutdown
  config.py        dataclasses + load_config(path) with the defaults above; validate times, days, timezone, masks
  schedule.py      is_allowed(dt_aware, ScheduleSettings) -> bool, using zoneinfo
  source.py        frame iterators: multipart /stream and /snapshot polling
  motion.py        MotionDetector.feed(jpeg_bytes) -> MotionResult(changed_percent, is_motion) | None for undecodable
  events.py        EventRecorder: pre-roll ring buffer and the event state machine; pure, clock injected
  storage.py       event directories, event.json, SHA256SUMS, latest.jpg, retention, crash recovery
```

### Behaviour

**Source (`source.py`)**

- `stream`: `httpx` streaming GET `http://<static_ip>/stream` with the bearer header.
  Read the boundary from the response `Content-Type` (`boundary=` parameter; strip quotes;
  the firmware sends `sentinel_mjpeg_boundary`). Parse parts yourself: find the boundary
  line, read headers to the blank line, then read `Content-Length` bytes when the header is
  present, else read up to the next boundary. Must work when parts are split across
  arbitrary network chunk sizes.
- `snapshot`: GET `/snapshot` at `snapshot_fps` with the same header.
- A frame is kept only if it starts with `FF D8` and contains `FF D9` in its last 16 bytes.
  Others count as `bad_frames_dropped` and are not saved.
- On connect error, timeout, non-200 or a stream that ends: log one line, back off
  1, 2, 4 … 30 s, reconnect. HTTP 401 logs "stream token rejected" and keeps retrying at 30 s.
- Yields `(utc_timestamp_float, jpeg_bytes)`.

**Motion (`motion.py`)**

- Decode with `Image.open(BytesIO(b))`, then
  `im.draft("L", (analysis_width, analysis_width * im.height // im.width))`, then `convert("L")`
  and resize to exactly that size. Draft mode makes libjpeg decode at a reduced scale
  (1/8 for a 1280×720 frame at width 160), so an HD frame costs very little.
- `ImageFilter.GaussianBlur(1)` on the small frame. The background is a running average
  kept with `Image.blend(background, frame, background_alpha)`; the first good frame
  seeds it.
- Diff = `ImageChops.difference(frame, background)`. Paint masked rectangles black.
  Changed pixels = count of diff values > `pixel_threshold` (use `point()` + `histogram()`).
  `changed_percent` is over unmasked pixels.
- `is_motion` becomes true after `trigger_frames` consecutive frames over
  `min_area_percent`, and stays true per frame while frames stay over it.
- Undecodable frame: return `None` (caller counts it as bad, does not save it).
- Keep feeding frames outside the schedule, so the background is current when the
  schedule opens.

**Events (`events.py`)**, a pure state machine, clock passed in, no I/O; it calls a storage interface

```text
WATCHING  every good frame goes into the pre-roll ring (pre_roll_seconds of frames, by timestamp)
WATCHING ──(is_motion and schedule allows)──► RECORDING: open event, write pre-roll frames, then each new frame
RECORDING: each motion frame resets the post-roll deadline
RECORDING ──(no motion for post_roll_seconds)──► close "no_motion" ──► WATCHING
RECORDING ──(max_event_seconds reached)──► close "max_length"; if still motion, open the next event immediately with no pre-roll gap
RECORDING ──(source disconnects)──► close "camera_offline"
RECORDING ──(SIGTERM)──► close "shutdown"
```

- The schedule is checked only when deciding to **open** an event. An event that is
  running when the quiet window starts finishes normally (post-roll or max length).
- `schedule.enabled = false` means the schedule always allows.

**Storage (`storage.py`)**

- Layout and file names exactly as in the frozen interface. Directory names use the
  config timezone; `event.json` times are UTC ISO 8601 with milliseconds and `Z`.
- Write frames with a plain open/write/close; `fsync` on close of the event only.
- `latest.jpg` every `latest_jpeg_seconds` (tmp file in the same dir, then `os.replace`).
- **Crash recovery** at start: any `event.json` with `end_utc: null` is finalized from its
  last frame's timestamp with `end_reason: "recorder_restart"` and gets its `SHA256SUMS`.
- **Retention** at start and then hourly: delete event directories whose start is older
  than `retain_days`; then, while the recordings tree is over `max_disk_gb`, delete the
  oldest event directory. Never delete an open event or `latest.jpg`. Remove empty date dirs.

**Logging:** one line per camera per minute: fps received, bad frames, max changed %,
`allowed`/`quiet`, state. One line per event open/close with its directory and reason.
Never log the token.

### Tests (`host/recorder/tests/`, pytest, no network except localhost)

Generate JPEG fixtures in the tests with Pillow (a grey 1280×720 frame; the same frame with
a dark 300×300 square pasted in; the same frame with ±3 random noise). Do not commit
binary fixtures.

| File | Must cover |
| --- | --- |
| `test_schedule.py` | Mon 05:59 allowed, Mon 06:00 quiet, Wed 12:00 quiet, Fri 15:59 quiet, Fri 16:00 allowed, Sat 12:00 allowed, Sun 23:59 allowed, Mon 00:30 allowed; both 2026 DST changes in `America/Chicago` (2026-03-08, 2026-11-01); a UTC input converted to local time; `enabled=false`; bad config (`"6am"`, unknown day, unknown zone) raises |
| `test_motion.py` | identical frames → no motion; noise → no motion; square appears → motion after exactly `trigger_frames`; a mask over the square → no motion; truncated JPEG → `None` |
| `test_source.py` | the multipart parser on recorded bytes split into 1, 7 and 4096-byte chunks; with and without `Content-Length`; quoted boundary; a corrupt part is dropped and the next one is kept |
| `test_events.py` | fake clock and fake storage: pre-roll frames written first and in order; post-roll close; motion during post-roll extends; `max_length` split with no frame lost between the two events; no event opens in the quiet window; an event running at 06:00 Monday finishes; disconnect closes `camera_offline` |
| `test_storage.py` | layout and names; `event.json` fields; `SHA256SUMS` verifies with `hashlib`; crash recovery; retention by age and by size; `latest.jpg` replaced atomically |
| `test_end_to_end.py` | a `http.server` thread on 127.0.0.1 serving `multipart/x-mixed-replace` from the generated JPEGs (static frames, then square frames, then static) with a token check; run one worker with `schedule.enabled=false`, `pre_roll_seconds=1`, `post_roll_seconds=1`; assert exactly one event directory with frames and a valid `SHA256SUMS`; wrong token → no event, a "token rejected" log line |

### Verify

```sh
cd host/recorder && python -m venv .venv && . .venv/bin/activate && pip install -e '.[dev]' && pytest -q
```

If `podman` is installed: `podman build -t localhost/sentinel-recorder:latest -f host/recorder/Containerfile host/recorder`
and `podman run --rm localhost/sentinel-recorder:latest check-schedule /etc/sentinel/recorder.toml --at 2026-10-19T17:00`
prints `allowed`.

### Out of scope

Installer, Quadlet units, docs outside `host/recorder/README.md`, MQTT, switching the camera
to `armed` while recording (possible follow-up), converting to MP4, any web UI, firmware.

### Exit and stop

`pytest` green, no ffmpeg/OpenCV/numpy import anywhere (`grep -rnE "ffmpeg|cv2|numpy" host/recorder` is empty
apart from this rule in the README). `host/recorder/README.md` explains config keys, the layout,
how to view an event, and `check-schedule`. Stop. Do not wire the installer.

---

## Prompt B — installer wiring, mode switch and docs

### Agent instructions

Wire simple mode into the installers and docs, following the frozen interface above. Do
not write or depend on `host/recorder/src/` (Prompt A builds it in parallel); treat
`host/recorder/Containerfile` and `host/recorder/config.toml` as existing at the paths given.
Read `host/scripts/install-services.sh`, `scripts/install-fedora.sh`,
`host/provision/sentinel_provision/__main__.py` (`render-frigate`), `cameras.py`,
`credentials.py` (`load_camera_secrets`) and their tests before editing. Keep their style:
idempotent, `install_if_changed`, restart only what changed, no secrets printed.

### Goal

1. **`sentinel-provision render-recorder --cameras a[,b,c] --timezone ZONE --out FILE --env-out FILE`**
   in `host/provision/`. It reads `host/recorder/config.toml` as the template, replaces the
   `[[cameras]]` tables with the selected cameras from `CAMERAS`, sets `schedule.timezone`,
   and writes the env file with only `SENTINEL_STREAM_TOKEN_<ID>=<token>` lines from
   `load_camera_secrets`. Both rendered files are written private (0600); the installer then
   installs `recorder.env` at 0600 and `recorder.toml` at 0644. Same unsafe-character check on tokens as
   `render_frigate_config`. Optional `--ignore-schedule` sets `schedule.enabled = false`.
   Write TOML with a small hand-written emitter for this flat schema (do not add a dependency).
2. **`host/quadlet/sentinel-recorder.container`** and **`host/quadlet/sentinel-recordings.volume`**
   per the frozen table. Model them on `sentinel-controller.container` and `sentinel-evidence.volume`.
   The container unit:
   - `[Unit]`: `After=network-online.target mosquitto.service`, `Wants=network-online.target`,
     `Conflicts=frigate.service sentinel-controller.service`. No `Requires=`: the recorder does not
     use MQTT.
   - `[Container]`: `EnvironmentFile=/etc/sentinel/recorder.env`,
     `Environment=SENTINEL_RECORDER_CONFIG=/etc/sentinel/recorder.toml`, the config mounted `ro,Z`,
     `sentinel-recordings.volume:/var/lib/sentinel/recordings:Z`. No `TZ=`; the config carries the zone.
   - `[Service]`: `Restart=always`. `[Install]`: `WantedBy=multi-user.target`.
3. **`host/scripts/install-services.sh --mode frigate|simple`**
   - No flag: use `/etc/sentinel/mode` if it exists, else `frigate`. Write the chosen mode back.
   - `--ignore-schedule` (simple mode only) passes through to `render-recorder`; it is not persisted.
   - Timezone: `timedatectl show -p Timezone --value`, falling back to `UTC` with a warning.
   - **frigate**: today's behaviour, unchanged. Additionally, if `$units/sentinel-recorder.container`
     exists: `systemctl stop sentinel-recorder.service`, remove the unit file.
   - **simple**: images: pull/pin mosquitto only (make `pin-digests.sh` skip Frigate when asked, or
     add a flag; keep its default behaviour). Install mosquitto as today. Stop `sentinel-controller`
     and `frigate` if active, remove their `.container` files from `$units` (keep every volume and
     `/etc/sentinel/frigate*` so switching back is one command). Build `localhost/sentinel-recorder:latest`
     the way the controller image is built. Render and `install_if_changed` the recorder config and env.
     Install `sentinel-recordings.volume` and `sentinel-recorder.container`. `daemon-reload`, start or
     restart, and verify `sentinel-recorder.service` is active plus the MQTT login checks that apply.
   - Quadlet units cannot be `systemctl disable`d; removing the `.container` file and `daemon-reload`
     is how a mode's units are turned off. Say so in a comment.
4. **`scripts/install-fedora.sh --mode frigate|simple`** and **`--ignore-schedule`**: pass through to
   `install-services.sh`. Help text and the end-of-run summary name the mode. Also add
   `install_local host/recorder` to `scripts/setup-python-venv.sh` (and its header comment), so the
   repo `.venv` can run the recorder tests.
5. **Docs**
   - `README.md`: a short "Modes" section: Frigate mode (default) vs simple mode, one table, the
     schedule rule in plain words, the one-camera command:
     `scripts/install-fedora.sh --mode simple --cameras a`. Switching back: `--mode frigate`.
   - `host/RUNBOOK.md`: "Simple mode" section: install, `journalctl -u sentinel-recorder -f`,
     daytime bench test with `--ignore-schedule` then re-run without it, where recordings are,
     `sudo cat .../latest.jpg` for aiming, `check-schedule`, switching modes.
   - `docs/phases/CONTRACTS.md`: a "Simple mode" section that links to the frozen interface in
     `07-simple-motion-mode.md` (do not copy it) and states that `/stream` and `/snapshot` are now
     consumed by two host clients (go2rtc or the recorder, never both).
   - `docs/PLAN.md`: one paragraph under Key designs and a Phase 7 checklist entry.
   - `docs/phases/README.md` already lists this brief; leave it.

### Tests

- `host/provision/tests/test_render_recorder.py`: one camera and three cameras; tokens only for the
  selected cameras; `--ignore-schedule`; the timezone lands in the file; output parses with `tomllib`
  and matches the frozen schema keys; files are 0600; an unsafe token is refused.
- `shellcheck` on every changed shell script, clean.
- `bash -n` on every changed shell script.

### Out of scope

The recorder's Python code (Prompt A), Frigate config, controller, firmware, the network/AP scripts.
**Do not edit `host/network/`**: the deployed box has unsynced Wi-Fi fixes there
([SYNC-DEPLOY-PC.md](SYNC-DEPLOY-PC.md) merges them).

### Exit and stop

Tests and shellcheck green. `install-services.sh --help` documents `--mode` and `--ignore-schedule`.
Stop. Real install on the host is a human step in the runbook.

---

## Prompt C (optional) — Frigate mode with fewer than three cameras

### Problem

`install-services.sh --cameras a` renders Frigate with one camera, but installs
`host/controller/config.toml` unchanged, which lists `sentinel_a`, `sentinel_b`, `sentinel_c`.
On a trigger the controller POSTs `sentinel_sync` for `sentinel_b`/`sentinel_c`, which do not
exist in Frigate. `create_sentinel_sync` raises on the HTTP error, so `_ensure_sync_events`
stops partway, and the evidence export batch also names the missing cameras.

### Goal

1. `sentinel-provision render-controller --cameras a --out FILE` writes the controller config from
   `host/controller/config.toml` with only the selected `[[cameras]]`. `install-services.sh` uses it
   instead of copying the file.
2. In `state_machine.py`, a failing `create_sentinel_sync` for one camera is logged and skipped, so the
   other cameras are still handled (test: one camera's create raises, the others still get events).

Tests in `host/provision/tests/` and `host/controller/tests/`, pytest green. Do not touch simple mode.

---

## Prompt D (optional, gated) — Frigate mode ffmpeg input errors

**Do not start** until all three are true:

1. [SYNC-DEPLOY-PC.md](SYNC-DEPLOY-PC.md) has been done, so the deployed box's changes are in the repo.
2. The deployed camera runs the newest firmware, and the errors are still there.
3. The human pasted the exact error lines into the chat, from
   `sudo journalctl -u frigate --since "15 min ago" | grep -iE "ffmpeg|go2rtc|error"` and the go2rtc
   log in Frigate's UI (Settings → Logs → go2rtc).

### Likely cause and fix

Today go2rtc's source is `ffmpeg:http://<ip>/stream?token=…#video=h264#hardware`, so ffmpeg's own
multipart demuxer parses the ESP32's HTTP stream, then VAAPI encodes it. Both steps commonly fail on
ESP32 cameras. go2rtc reads HTTP MJPEG natively (`docs/vendor/go2rtc/README.md`, "Source: HTTP"), so
the fix is to give ffmpeg go2rtc's own restream instead of the camera's HTTP:

```yaml
go2rtc:
  streams:
    sentinel_a_mjpeg: "http://10.77.0.11/stream?token={FRIGATE_STREAM_TOKEN_A}"
    sentinel_a: "ffmpeg:sentinel_a_mjpeg#video=h264#hardware"
```

Map the pasted errors:

| Error text contains | Change |
| --- | --- |
| `mpjpeg`, `Expected boundary`, `Invalid data found when processing input`, `could not find codec parameters` | the two-stream chain above |
| `vaapi`, `hwupload`, `Impossible to convert between the formats`, `Failed to initialise VAAPI` | also drop `#hardware` (CPU libx264 at 720p 5 fps is fine on an i7) |
| `401` | stream token mismatch: regenerate the Frigate config, do not change formats |
| anything else | stop, report it, change nothing |

Update `host/frigate/config.yml`, `GO2RTC_STREAM_LINE` and `add_camera_to_text` in
`host/provision/sentinel_provision/frigate_config.py` (the stream-exists check must recognise both
lines), the go2rtc source shape in `CONTRACTS.md`, and the tests in
`host/provision/tests/test_install_flow.py`. Pytest green. Stop: the human restarts Frigate and checks.
