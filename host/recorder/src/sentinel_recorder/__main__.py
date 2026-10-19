from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sentinel_recorder.config import Camera, Config, load_config, resolve_config_path
from sentinel_recorder.events import EventRecorder
from sentinel_recorder.motion import MotionDetector
from sentinel_recorder.schedule import is_allowed
from sentinel_recorder.source import BadFrame, GoodFrame, SourceDown, iter_frames
from sentinel_recorder.storage import Storage

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("sentinel_recorder")


def main(argv: list[str] | None = None) -> None:
    if argv is None:
        argv = sys.argv[1:]
    else:
        argv = list(argv)
    if argv and argv[0] == "check-schedule":
        raise SystemExit(_check_schedule(argv[1:]))
    raise SystemExit(_run(argv))


def run_camera(camera: Camera, cfg: Config, storage: Storage, stop: threading.Event) -> None:
    token = os.environ.get(f"SENTINEL_STREAM_TOKEN_{camera.id.upper()}", "")
    recorder = EventRecorder(camera.frigate_name, cfg.recorder, cfg.schedule, storage)
    detector = MotionDetector(cfg.motion)
    window_start = time.monotonic()
    received = 0
    bad = 0
    max_changed = 0.0
    try:
        for item in iter_frames(camera, cfg.recorder, token, stop):
            if stop.is_set():
                break
            now = datetime.now(timezone.utc)
            if isinstance(item, SourceDown):
                detector.reset()
                recorder.on_disconnect(item.timestamp)
            elif isinstance(item, BadFrame):
                received += 1
                bad += 1
                recorder.note_bad_frame()
            elif isinstance(item, GoodFrame):
                received += 1
                result = detector.feed(item.jpeg)
                if result is None:
                    bad += 1
                    recorder.note_bad_frame()
                else:
                    max_changed = max(max_changed, result.changed_percent)
                    when = datetime.fromtimestamp(item.timestamp, tz=timezone.utc)
                    recorder.on_frame(item.timestamp, item.jpeg, result.is_motion, when)
                    storage.write_latest(camera.frigate_name, item.jpeg, item.timestamp)
                    now = when
            elapsed = time.monotonic() - window_start
            if elapsed >= 60:
                _log_minute(camera, received, bad, max_changed, elapsed, now, cfg, recorder)
                window_start = time.monotonic()
                received = 0
                bad = 0
                max_changed = 0.0
    finally:
        recorder.on_shutdown(time.time())


def _log_minute(camera, received, bad, max_changed, elapsed, now, cfg, recorder) -> None:
    label = "allowed" if is_allowed(now, cfg.schedule) else "quiet"
    logger.info(
        "%s fps=%.2f bad=%d max_changed=%.2f %s %s",
        camera.frigate_name,
        received / elapsed,
        bad,
        max_changed,
        label,
        recorder.state_name,
    )


def _check_schedule(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="sentinel-recorder check-schedule")
    parser.add_argument("config", nargs="?")
    parser.add_argument("--at", dest="at")
    args = parser.parse_args(argv)
    try:
        cfg = load_config(resolve_config_path(args.config))
        zone = ZoneInfo(cfg.schedule.timezone)
        when = _parse_at(args.at, zone) if args.at else datetime.now(zone)
        allowed = is_allowed(when, cfg.schedule)
    except (OSError, ValueError) as exc:
        print(f"sentinel-recorder: {exc}", file=sys.stderr)
        return 2
    print("allowed" if allowed else "quiet")
    return 0 if allowed else 1


def _parse_at(value: str, zone: ZoneInfo) -> datetime:
    moment = datetime.fromisoformat(value)
    if moment.tzinfo is None:
        return moment.replace(tzinfo=zone)
    return moment


def _run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="sentinel-recorder")
    parser.add_argument("config", nargs="?")
    args = parser.parse_args(argv)
    try:
        cfg = load_config(resolve_config_path(args.config))
    except (OSError, ValueError) as exc:
        print(f"sentinel-recorder: {exc}", file=sys.stderr)
        return 2

    stop = threading.Event()

    def _stop(_signum, _frame) -> None:
        stop.set()

    previous_int = signal.getsignal(signal.SIGINT)
    previous_term = signal.getsignal(signal.SIGTERM)
    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    try:
        return _run_until_stop(cfg, stop)
    finally:
        signal.signal(signal.SIGINT, previous_int)
        signal.signal(signal.SIGTERM, previous_term)


def _run_until_stop(cfg: Config, stop: threading.Event) -> int:
    recordings = Path(cfg.recorder.recordings_dir)
    try:
        _require_writable(recordings)
    except OSError as exc:
        print(
            f"sentinel-recorder: cannot write {recordings}: {exc} (uid {os.getuid()})",
            file=sys.stderr,
        )
        return 2

    storage = Storage(cfg.recorder, cfg.schedule.timezone)
    recovered = storage.recover()
    if recovered:
        logger.info("recovered %d open event(s)", recovered)
    storage.enforce_retention(time.time())

    failed = threading.Event()
    threads: list[threading.Thread] = []
    for camera in cfg.cameras:
        thread = threading.Thread(
            target=_run_camera,
            name=f"recorder-{camera.id}",
            args=(camera, cfg, storage, stop, failed),
        )
        thread.start()
        threads.append(thread)

    next_retention = time.monotonic() + 3600
    while not stop.wait(1.0):
        if time.monotonic() >= next_retention:
            storage.enforce_retention(time.time())
            next_retention = time.monotonic() + 3600

    for thread in threads:
        thread.join(timeout=cfg.recorder.read_timeout_seconds + 5)
    return 1 if failed.is_set() else 0


def _run_camera(
    camera: Camera,
    cfg: Config,
    storage: Storage,
    stop: threading.Event,
    failed: threading.Event,
) -> None:
    try:
        run_camera(camera, cfg, storage, stop)
    except Exception:
        logger.exception("camera worker %s failed", camera.frigate_name)
        failed.set()
        stop.set()


def _require_writable(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    probe = path / f".probe-{os.getpid()}"
    try:
        with probe.open("wb") as handle:
            handle.write(b"")
    finally:
        try:
            probe.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    main()
