# Phase 7 follow-up: fixes from the review of Prompts A and B

**Kind:** two coding agent prompts (fresh chats)  
**Model:** Composer 2.5 Fast (`composer-2.5-fast`) for both  
**Parent brief:** [07-simple-motion-mode.md](07-simple-motion-mode.md). Its frozen interface still applies.

| Prompt | Owns these files | Can run with |
| --- | --- | --- |
| **A2 — recorder robustness** | `host/recorder/src/`, `host/recorder/tests/`, `host/recorder/README.md` | B2 |
| **B2 — install permissions and checks** | `host/scripts/install-services.sh`, `host/recorder/Containerfile`, `host/controller/Containerfile`, `host/RUNBOOK.md`, repo-root `test.log` | A2 |

Paste one prompt section per fresh chat. Neither prompt edits the other's files.

## What the review found (for context; both prompts)

Checked on the Arch dev box: recorder 43 tests, provision 25 and controller 8 all pass;
shellcheck is clean; no ffmpeg, OpenCV or numpy. The design matches the brief. The problems are
in what the tests do not exercise: running as the container user, and failing loudly.

1. **Blocker.** `install-services.sh` installs `/etc/sentinel/recorder.toml` at mode 0600, owned
   by root. The container runs as uid 1000 (rootful podman, no user namespace), so it cannot read
   its own config. It exits 2 at every start and systemd restart-loops it. (The parent brief asked
   for 0600 by mistake; it is corrected now.)
2. **Blocker, very likely.** Nothing in the image creates `/var/lib/sentinel/recordings`, so the
   new `sentinel-recordings` volume is root-owned and uid 1000 cannot write it.
3. **Silent failure, reproduced.** When a camera worker thread raises (for example the permission
   error above, or a full disk), the thread dies and the process keeps running. `systemctl status`
   says "active (running)" while nothing is recorded. Reproduced on the dev box: one
   `PermissionError` traceback, then the process stays up until killed.
4. Retention holds the storage lock while it re-walks the whole recordings tree once per deleted
   event. Near the disk cap (about a million frame files) that can stall every camera thread for
   minutes. The camera threads block on the same lock in `write_latest`.
5. Closing an event re-reads and hashes every frame (up to about 300 MB for a 15-minute event)
   and fsyncs every file while holding the shared lock. During continuous motion, the
   `max_length` split leaves a gap of a few seconds.
6. After a camera outage the motion background is stale, so the first frames after a reconnect
   (lights changed, camera rebooted) record a spurious event of about 35 s.
7. A malformed `Content-Length` header raises `ValueError` and drops the whole connection,
   instead of dropping just that part.

---

## Prompt A2 — recorder robustness

### Agent instructions

Fix items 3–7 above in `host/recorder/src/sentinel_recorder/` with tests in `host/recorder/tests/`.
Keep the frozen interface in [07-simple-motion-mode.md](07-simple-motion-mode.md) unchanged: CLI,
config keys, environment variables, on-disk layout, `event.json` fields, the `SHA256SUMS` format.
Do not touch `Containerfile`, `config.toml`, anything outside `host/recorder/`, or the
`EventRecorder` state machine's behaviour (its tests must keep passing unchanged). Read the existing
modules and tests first, and match their style.

### Changes

1. **Fail loudly (`__main__.py`).**
   - Before any thread starts, create `recordings_dir` if it is missing, then write and delete a
     probe file in it. On `OSError`, print one line to stderr naming the path, the error and
     `os.getuid()`, and return exit code 2.
   - Wrap each camera worker so that an unexpected exception is logged with `logger.exception`,
     records that a worker failed, and sets the shared `stop` event.
   - The main loop already waits on `stop`. After joining the threads, `_run` returns **1** if any
     worker failed, else 0. systemd's `Restart=always` then restarts the container, and the failure
     shows in `systemctl status`.
2. **Retention without stalls (`storage.py`).**
   - Track open events in memory: a set of event paths, added in `open_event`, removed in
     `close_event`. `enforce_retention` skips paths in that set as well as events with
     `end_utc: null`.
   - One pass: list the events, compute each event directory's size once, delete closed events
     older than `retain_days`, then delete the oldest closed events until the summed sizes are
     ≤ `max_disk_gb`. Do not re-walk the tree per deletion.
   - Hold `self._lock` only to copy the open-event set and for directory creation. Never hold it
     while walking, hashing, deleting or fsyncing.
3. **Cheaper close (`storage.py`).**
   - `write_frame` hashes the bytes it already holds (`hashlib.sha256(jpeg)`) and keeps the digest
     with the event's in-memory record.
   - `close_event` writes `SHA256SUMS` from those digests, plus `event.json` hashed from disk, with
     no re-read of frame files. Keep the fsync of the event's files and directories, outside the lock.
   - `recover()` (no in-memory digests after a crash) keeps hashing from disk.
   - `SHA256SUMS` content and order (sorted relative paths) must be identical to today's.
4. **Reconnect does not fake motion (`motion.py`, `__main__.py`).** Add `MotionDetector.reset()`
   (drop the background, zero the streak). Call it on every `SourceDown`.
5. **Bad `Content-Length` (`source.py`).** If the header value is not a non-negative integer, treat
   the part as having no `Content-Length` (scan to the next boundary). The connection stays up.

### Tests

| Test | Asserts |
| --- | --- |
| worker failure | a fake storage whose `write_frame` raises `OSError` and the fake camera server from `test_end_to_end.py`: `_run` (or a thin testable wrapper) returns 1 within 10 s, and the log has the traceback |
| unwritable dir | `recordings_dir` is a read-only directory (`chmod 0o555`; skip the test when running as root): exit code 2 and the path appears on stderr |
| retention single walk | over the cap with 20 closed events: the oldest are deleted until the total is under the cap, an in-memory open event is never deleted, and each event directory is walked once (count calls with a monkeypatched `os.walk`) |
| sums from memory | after close, `SHA256SUMS` verifies with `hashlib`; monkeypatch `Path.read_bytes` to fail for `frames/*.jpg` during `close_event` and it still succeeds |
| reset | after `reset()`, a frame very different from the old background gives `is_motion = False` (the first frame seeds) |
| bad header | a part with `Content-Length: abc`, then a good part: the parser returns the good JPEG and does not raise |

### Verify

From `host/recorder`: `pip install -e '.[dev]' && pytest -q`, all green, including every pre-existing
test unchanged.

### Stop

Do not change the installer, the Containerfile or the docs outside `host/recorder/README.md`. Add one
README line: the process exits non-zero when a camera worker fails, so `systemctl status` shows it.

---

## Prompt B2 — install permissions and post-install checks

### Agent instructions

Fix items 1 and 2 above, and make the installer prove that the recorder can read its config and write
its volume. Read `host/scripts/install-services.sh` (simple-mode branches), `host/recorder/Containerfile`,
`host/quadlet/sentinel-recorder.container` and `host/quadlet/sentinel-recordings.volume` first. Keep the
script's style: idempotent, `install_if_changed`, restart only what changed, no secrets printed. Do not
edit `host/recorder/src/` or its tests (Prompt A2 owns them).

### Changes

1. **Config mode.** In `install-services.sh`, install `$etc/recorder.toml` at **0644**. It holds no
   secrets. `$etc/recorder.env` (tokens) stays 0600; podman reads it as root.
2. **Image directory.** In `host/recorder/Containerfile`, before `USER sentinel`:
   `RUN mkdir -p /var/lib/sentinel/recordings && chown sentinel:sentinel /var/lib/sentinel/recordings`.
   Podman copies the mount point's ownership into a new, empty named volume.
3. **Existing volume repair.** Simple mode, after `systemctl daemon-reload` and before starting the
   recorder:
   - `systemctl start sentinel-recordings-volume.service` (Quadlet's generated unit for
     `sentinel-recordings.volume`; it creates the volume).
   - Then `chown 1000:1000 "$(podman volume inspect sentinel-recordings --format '{{.Mountpoint}}')"`.
   - **Not recursive**: only the volume's top directory. This repairs a volume an earlier run created
     root-owned.
   - Do **not** use the `:U` volume option. It re-chowns every file recursively at each start, and
     this volume holds up to about a million frames.
4. **Simple-mode verify**, after `verify_unit sentinel-recorder`:
   - `podman exec sentinel-recorder sentinel-recorder check-schedule`: exit 0 or 1 is OK (it read the
     config); anything else is `FAIL` with the hint `recorder cannot read /etc/sentinel/recorder.toml`.
   - `podman exec sentinel-recorder sh -c 'test -w /var/lib/sentinel/recordings'`: on failure, `FAIL`
     with the hint `volume not writable by uid 1000`.
   - Then wait up to 20 s for `<volume mountpoint>/<frigate_name>/latest.jpg` of each selected camera
     to have an mtime newer than the install's start: `ok` if so. If not, print a **note** (not a
     failure): `no frame from <camera> yet; is it powered and on the AP? journalctl -u sentinel-recorder -f`.
   - Set `rc=1` only for the two `FAIL`s.
5. **Same class, controller (Frigate mode).** `host/controller/Containerfile` has the same gap for
   `/var/lib/sentinel/evidence` (the `sentinel-evidence` volume; the controller also runs as uid 1000).
   - Apply step 2's `mkdir`/`chown` there.
   - In frigate mode, apply step 3 to `sentinel-evidence` (its generated unit is
     `sentinel-evidence-volume.service`).
   - Add a matching `podman exec sentinel-controller sh -c 'test -w /var/lib/sentinel/evidence'` check.
6. **RUNBOOK.** In "Simple mode", add two troubleshooting lines: config-permission and
   volume-permission symptoms (the recorder exits with code 2, or `systemctl status` shows
   restart loops), and the fix (re-run the installer).
7. Delete the stray empty `test.log` at the repo root.

### Tests

- `shellcheck` and `bash -n` on `install-services.sh`, clean.
- Existing `host/provision` pytest still green (the renderer still writes its temporary output 0600;
  that is correct and unchanged).
- If `podman` works on this machine (`podman info` succeeds):
  - Build the recorder image.
  - Run `podman run --rm -v "$PWD/host/recorder/config.toml:/etc/sentinel/recorder.toml:ro" localhost/sentinel-recorder:latest check-schedule --at 2026-10-19T17:00`
    with the file at 0644, and see `allowed`.
  - Run `podman volume create t-rec && podman run --rm -v t-rec:/var/lib/sentinel/recordings --entrypoint sh localhost/sentinel-recorder:latest -c 'test -w /var/lib/sentinel/recordings && echo writable'`,
    then `podman volume rm t-rec`.
  - Otherwise say in the report that these two container checks were not run.

### Stop

Do not run the installer for real and do not touch `/etc`. The real install is the human's step in
the runbook.
