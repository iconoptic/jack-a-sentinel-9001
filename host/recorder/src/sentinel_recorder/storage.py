from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from sentinel_recorder import __version__
from sentinel_recorder.config import RecorderSettings

logger = logging.getLogger(__name__)

_FRAME_NAME = re.compile(r"^(\d{6})_(\d+)\.jpg$")
_DATE_DIR = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class _DiskEvent:
    path: Path
    start_utc: float
    is_open: bool


class Storage:
    def __init__(self, recorder: RecorderSettings, timezone_name: str) -> None:
        self.recorder = recorder
        self.timezone_name = timezone_name
        self.root = Path(recorder.recordings_dir)
        self._lock = threading.Lock()
        self._latest_at: dict[str, float] = {}
        self._open: set[Path] = set()
        self._digests: dict[Path, dict[str, str]] = {}

    def open_event(self, *, camera: str, start_utc: float, pre_roll_frames: int) -> Path:
        with self._lock:
            event_dir = self._make_event_dir(camera, start_utc)
            self._open.add(event_dir)
            self._digests[event_dir] = {}
            self._write_json(
                event_dir / "event.json",
                _event_document(
                    camera=camera,
                    start_utc=start_utc,
                    end_utc=None,
                    timezone_name=self.timezone_name,
                    frames=0,
                    pre_roll_frames=pre_roll_frames,
                    bad_frames_dropped=0,
                    end_reason=None,
                ),
            )
        logger.info("event open %s", event_dir)
        return event_dir

    def write_frame(self, event: Path, seq: int, ts: float, jpeg: bytes) -> None:
        frames = event / "frames"
        frames.mkdir(parents=True, exist_ok=True)
        name = f"{seq:06d}_{int(round(ts * 1000))}.jpg"
        path = frames / name
        with path.open("wb") as handle:
            handle.write(jpeg)
        digest = hashlib.sha256(jpeg).hexdigest()
        with self._lock:
            self._digests.setdefault(event, {})[f"frames/{name}"] = digest

    def close_event(
        self,
        event: Path,
        *,
        end_utc: float,
        end_reason: str,
        frames: int,
        pre_roll_frames: int,
        bad_frames_dropped: int,
    ) -> None:
        with self._lock:
            stored = self._digests.get(event)
            digests = None if stored is None else dict(stored)
        self._finalize(
            event,
            end_utc=end_utc,
            end_reason=end_reason,
            frames=frames,
            pre_roll_frames=pre_roll_frames,
            bad_frames_dropped=bad_frames_dropped,
            digests=digests,
        )
        with self._lock:
            self._open.discard(event)
            self._digests.pop(event, None)

    def write_latest(self, camera: str, jpeg: bytes, now: float) -> None:
        interval = self.recorder.latest_jpeg_seconds
        if interval <= 0:
            return
        with self._lock:
            previous = self._latest_at.get(camera, float("-inf"))
            if now - previous < interval:
                return
            camera_dir = self.root / camera
            camera_dir.mkdir(parents=True, exist_ok=True)
            tmp = camera_dir / f".latest.{os.getpid()}.tmp"
            with tmp.open("wb") as handle:
                handle.write(jpeg)
            os.replace(tmp, camera_dir / "latest.jpg")
            self._latest_at[camera] = now

    def recover(self) -> int:
        count = 0
        for item in self._scan():
            if not item.is_open:
                continue
            end_utc, frame_count = _last_frame(item.path)
            document = _read_json(item.path / "event.json")
            if end_utc is None:
                end_utc = item.start_utc
            self._finalize(
                item.path,
                end_utc=end_utc,
                end_reason="recorder_restart",
                frames=frame_count,
                pre_roll_frames=int(document.get("pre_roll_frames") or 0),
                bad_frames_dropped=int(document.get("bad_frames_dropped") or 0),
            )
            count += 1
        return count

    def enforce_retention(self, now: float) -> None:
        with self._lock:
            open_events = set(self._open)
        cutoff = now - self.recorder.retain_days * 86400
        items = self._scan()
        sizes = {item.path: _event_bytes(item.path) for item in items}
        for item in items:
            if self._retain(item, open_events):
                continue
            if item.start_utc < cutoff:
                _remove_tree(item.path)
                sizes[item.path] = 0
        limit = self.recorder.max_disk_gb * (1024**3)
        total = sum(sizes.values())
        closed = [
            item
            for item in items
            if not self._retain(item, open_events) and sizes[item.path] > 0
        ]
        closed.sort(key=lambda item: (item.start_utc, str(item.path)))
        for item in closed:
            if total <= limit:
                break
            _remove_tree(item.path)
            total -= sizes[item.path]
            sizes[item.path] = 0
        self._remove_empty_date_dirs()

    def _retain(self, item: _DiskEvent, open_events: set[Path]) -> bool:
        if item.is_open or item.path in open_events:
            return True
        with self._lock:
            return item.path in self._open

    def _make_event_dir(self, camera: str, start_utc: float) -> Path:
        local = datetime.fromtimestamp(start_utc, ZoneInfo(self.timezone_name))
        day = self.root / camera / local.strftime("%Y-%m-%d")
        day.mkdir(parents=True, exist_ok=True)
        base = local.strftime("%H-%M-%S")
        candidate = day / base
        suffix = 2
        while candidate.exists():
            candidate = day / f"{base}-{suffix}"
            suffix += 1
        (candidate / "frames").mkdir(parents=True)
        return candidate

    def _finalize(
        self,
        event_dir: Path,
        *,
        end_utc: float,
        end_reason: str,
        frames: int,
        pre_roll_frames: int,
        bad_frames_dropped: int,
        digests: dict[str, str] | None = None,
    ) -> None:
        document = _read_json(event_dir / "event.json")
        self._write_json(
            event_dir / "event.json",
            _event_document(
                camera=str(document.get("camera", "")),
                start_utc=_parse_utc(str(document["start_utc"])),
                end_utc=end_utc,
                timezone_name=str(document.get("timezone", self.timezone_name)),
                frames=frames,
                pre_roll_frames=pre_roll_frames,
                bad_frames_dropped=bad_frames_dropped,
                end_reason=end_reason,
                version=str(document.get("recorder_version", __version__)),
            ),
        )
        _write_sums(event_dir, digests)
        _fsync_tree(event_dir)
        logger.info("event close %s reason=%s", event_dir, end_reason)

    def _scan(self) -> list[_DiskEvent]:
        if not self.root.is_dir():
            return []
        found: list[_DiskEvent] = []
        for event_json in self.root.glob("*/*/*/event.json"):
            try:
                document = _read_json(event_json)
                start = _parse_utc(str(document["start_utc"]))
            except (OSError, json.JSONDecodeError, KeyError, ValueError):
                logger.warning("skip unreadable event %s", event_json)
                continue
            found.append(_DiskEvent(event_json.parent, start, document.get("end_utc") is None))
        return found

    def _remove_empty_date_dirs(self) -> None:
        if not self.root.is_dir():
            return
        for camera_dir in self.root.iterdir():
            if not camera_dir.is_dir():
                continue
            for date_dir in camera_dir.iterdir():
                if date_dir.is_dir() and _DATE_DIR.fullmatch(date_dir.name):
                    try:
                        date_dir.rmdir()
                    except OSError:
                        pass

    def _write_json(self, path: Path, document: dict) -> None:
        payload = (json.dumps(document, indent=2) + "\n").encode("utf-8")
        tmp = path.with_name(path.name + ".tmp")
        with tmp.open("wb") as handle:
            handle.write(payload)
        os.replace(tmp, path)


def format_utc_ms(ts: float) -> str:
    millis = int(round(ts * 1000.0))
    seconds, millis = divmod(millis, 1000)
    moment = datetime.fromtimestamp(seconds, tz=timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + f"{millis:03d}Z"


def _event_document(
    *,
    camera: str,
    start_utc: float,
    end_utc: float | None,
    timezone_name: str,
    frames: int,
    pre_roll_frames: int,
    bad_frames_dropped: int,
    end_reason: str | None,
    version: str = __version__,
) -> dict:
    return {
        "camera": camera,
        "start_utc": format_utc_ms(start_utc),
        "end_utc": None if end_utc is None else format_utc_ms(end_utc),
        "timezone": timezone_name,
        "frames": frames,
        "pre_roll_frames": pre_roll_frames,
        "bad_frames_dropped": bad_frames_dropped,
        "end_reason": end_reason,
        "recorder_version": version,
    }


def _parse_utc(text: str) -> float:
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text).timestamp()


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _last_frame(event_dir: Path) -> tuple[float | None, int]:
    best_seq = -1
    best_ts: float | None = None
    count = 0
    frames = event_dir / "frames"
    if not frames.is_dir():
        return None, 0
    for path in frames.iterdir():
        match = _FRAME_NAME.fullmatch(path.name)
        if match is None or not path.is_file() or path.stat().st_size == 0:
            continue
        count += 1
        seq = int(match.group(1))
        if seq >= best_seq:
            best_seq = seq
            best_ts = int(match.group(2)) / 1000.0
    return best_ts, count


def _write_sums(event_dir: Path, digests: dict[str, str] | None = None) -> None:
    if digests is None:
        digests = {}
        for dirpath, _dirnames, names in os.walk(event_dir):
            for name in names:
                if name == "SHA256SUMS" or name.endswith(".tmp"):
                    continue
                path = Path(dirpath) / name
                rel = path.relative_to(event_dir).as_posix()
                digests[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    else:
        digests = dict(digests)
        event_json = event_dir / "event.json"
        digests[event_json.relative_to(event_dir).as_posix()] = hashlib.sha256(
            event_json.read_bytes()
        ).hexdigest()
    lines: list[str] = []
    for path in sorted(event_dir / rel for rel in digests):
        relative = path.relative_to(event_dir).as_posix()
        lines.append(f"{digests[relative]}  {relative}")
    text = ("\n".join(lines) + "\n") if lines else ""
    target = event_dir / "SHA256SUMS"
    tmp = target.with_name("SHA256SUMS.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, target)


def _fsync_tree(event_dir: Path) -> None:
    for dirpath, _dirnames, names in os.walk(event_dir):
        for name in names:
            _fsync(Path(dirpath) / name)
        _fsync(Path(dirpath))
    _fsync(event_dir)


def _fsync(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _remove_tree(path: Path) -> None:
    if not path.is_dir():
        return
    for child in path.iterdir():
        if child.is_dir():
            _remove_tree(child)
        else:
            child.unlink(missing_ok=True)
    path.rmdir()


def _event_bytes(path: Path) -> int:
    total = 0
    for dirpath, _dirnames, names in os.walk(path):
        for name in names:
            try:
                total += os.path.getsize(os.path.join(dirpath, name))
            except OSError:
                continue
    return total
