from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from sentinel_recorder.config import RecorderSettings
from sentinel_recorder.storage import Storage, format_utc_ms

UTC = timezone.utc


def _storage(tmp_path: Path, **overrides) -> Storage:
    fields: dict = {"recordings_dir": tmp_path, "latest_jpeg_seconds": 0}
    fields.update(overrides)
    return Storage(RecorderSettings(**fields), "UTC")


def _sums_from_disk(event: Path) -> str:
    files: list[Path] = []
    for dirpath, _dirnames, names in os.walk(event):
        for name in names:
            if name == "SHA256SUMS" or name.endswith(".tmp"):
                continue
            files.append(Path(dirpath) / name)
    lines = [
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(event).as_posix()}"
        for path in sorted(files)
    ]
    return ("\n".join(lines) + "\n") if lines else ""


def _open_pair(storage: Storage, start: float) -> Path:
    event = storage.open_event(camera="sentinel_a", start_utc=start, pre_roll_frames=1)
    storage.write_frame(event, 1, start, b"\xff\xd8\xff\xd9")
    storage.close_event(
        event,
        end_utc=start + 1,
        end_reason="no_motion",
        frames=1,
        pre_roll_frames=1,
        bad_frames_dropped=0,
    )
    return event


def test_layout_names_and_sums(tmp_path: Path) -> None:
    storage = Storage(
        RecorderSettings(recordings_dir=tmp_path, latest_jpeg_seconds=0),
        "America/Chicago",
    )
    start = datetime(2026, 10, 19, 22, 42, 8, 123000, tzinfo=UTC).timestamp()
    event = storage.open_event(camera="sentinel_a", start_utc=start, pre_roll_frames=2)
    assert event.parent.name == "2026-10-19"
    assert event.name == "17-42-08"
    storage.write_frame(event, 1, start, b"\xff\xd8one\xff\xd9")
    storage.write_frame(event, 2, start + 0.201, b"\xff\xd8two\xff\xd9")
    storage.close_event(
        event,
        end_utc=start + 1.5,
        end_reason="no_motion",
        frames=2,
        pre_roll_frames=2,
        bad_frames_dropped=0,
    )
    document = json.loads((event / "event.json").read_text(encoding="utf-8"))
    assert document["camera"] == "sentinel_a"
    assert document["start_utc"] == format_utc_ms(start)
    assert document["end_utc"] == format_utc_ms(start + 1.5)
    assert document["timezone"] == "America/Chicago"
    assert document["frames"] == 2
    assert document["pre_roll_frames"] == 2
    assert document["bad_frames_dropped"] == 0
    assert document["end_reason"] == "no_motion"
    assert document["recorder_version"] == "0.1.0"
    names = sorted(path.name for path in (event / "frames").iterdir())
    assert names[0].startswith("000001_")
    assert names[1].startswith("000002_")
    assert names[0].endswith(".jpg")
    for line in (event / "SHA256SUMS").read_text(encoding="utf-8").splitlines():
        digest, rel = line.split("  ", 1)
        assert hashlib.sha256((event / rel).read_bytes()).hexdigest() == digest
    again = storage.open_event(camera="sentinel_a", start_utc=start, pre_roll_frames=0)
    assert again.name == "17-42-08-2"


def test_crash_recovery(tmp_path: Path) -> None:
    storage = _storage(tmp_path)
    start = 1_792_449_728.0
    later = start + 1.25
    event = storage.open_event(camera="sentinel_a", start_utc=start, pre_roll_frames=0)
    storage.write_frame(event, 1, start, b"\xff\xd8\x00\xff\xd9")
    storage.write_frame(event, 2, later, b"\xff\xd8\x01\xff\xd9")
    assert json.loads((event / "event.json").read_text(encoding="utf-8"))["end_utc"] is None

    revived = _storage(tmp_path)
    assert revived.recover() == 1
    document = json.loads((event / "event.json").read_text(encoding="utf-8"))
    assert document["end_reason"] == "recorder_restart"
    assert document["end_utc"] == format_utc_ms(later)
    assert document["frames"] == 2
    assert (event / "SHA256SUMS").is_file()


def test_retention_by_age_and_size(tmp_path: Path) -> None:
    now = datetime(2026, 10, 19, 12, 0, tzinfo=UTC).timestamp()
    storage = _storage(tmp_path, retain_days=30, max_disk_gb=100)
    old = _open_pair(storage, now - 40 * 86400)
    recent = _open_pair(storage, now - 86400)
    storage.enforce_retention(now)
    assert not old.exists()
    assert recent.exists()
    assert not old.parent.exists()

    sized = _storage(tmp_path, retain_days=10000, max_disk_gb=0, latest_jpeg_seconds=1)
    open_event = sized.open_event(camera="sentinel_a", start_utc=now, pre_roll_frames=0)
    sized.write_frame(open_event, 1, now, b"\xff\xd8open\xff\xd9")
    sized.write_latest("sentinel_a", b"aim", now)
    sized.enforce_retention(now)
    assert open_event.is_dir()
    assert json.loads((open_event / "event.json").read_text(encoding="utf-8"))["end_utc"] is None
    assert (tmp_path / "sentinel_a" / "latest.jpg").read_bytes() == b"aim"
    assert not recent.exists()


def test_retention_walks_each_event_once(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime(2026, 10, 19, 12, 0, tzinfo=UTC).timestamp()
    storage = _storage(tmp_path, retain_days=10000, max_disk_gb=100)
    closed: list[Path] = []
    for index in range(20):
        start = now - (20 - index) * 60
        event = storage.open_event(camera="sentinel_a", start_utc=start, pre_roll_frames=0)
        storage.write_frame(event, 1, start, b"\xff\xd8" + bytes([index]) * 2048 + b"\xff\xd9")
        storage.close_event(
            event,
            end_utc=start + 1,
            end_reason="no_motion",
            frames=1,
            pre_roll_frames=0,
            bad_frames_dropped=0,
        )
        closed.append(event)
    open_event = storage.open_event(camera="sentinel_a", start_utc=now - 100000, pre_roll_frames=0)
    storage.write_frame(open_event, 1, now - 100000, b"\xff\xd8" + b"o" * 2048 + b"\xff\xd9")
    # Closed on disk, still open in memory: only the in-memory set may save it.
    document = json.loads((open_event / "event.json").read_text(encoding="utf-8"))
    document["end_utc"] = format_utc_ms(now)
    (open_event / "event.json").write_text(json.dumps(document), encoding="utf-8")

    def size_of(path: Path) -> int:
        return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())

    kept = closed[-5:]
    cap = size_of(open_event) + sum(size_of(event) for event in kept)
    storage.recorder = replace(storage.recorder, max_disk_gb=cap / (1024**3))

    walked: list[Path] = []
    real_walk = os.walk

    def counting_walk(top, *args, **kwargs):
        walked.append(Path(top))
        return real_walk(top, *args, **kwargs)

    monkeypatch.setattr(os, "walk", counting_walk)
    storage.enforce_retention(now)

    for event in closed[:-5]:
        assert not event.exists()
    for event in kept:
        assert event.is_dir()
    assert open_event.is_dir()
    kept_document = json.loads((open_event / "event.json").read_text(encoding="utf-8"))
    assert kept_document["end_utc"] == format_utc_ms(now)
    for event in closed + [open_event]:
        assert walked.count(event) == 1
    assert len(walked) == len(closed) + 1


def test_close_hashes_frames_from_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    storage = _storage(tmp_path)
    start = 1_792_449_728.0
    event = storage.open_event(camera="sentinel_a", start_utc=start, pre_roll_frames=0)
    storage.write_frame(event, 1, start, b"\xff\xd8one\xff\xd9")
    storage.write_frame(event, 2, start + 0.5, b"\xff\xd8two\xff\xd9")
    real_read = Path.read_bytes

    def guarded(self: Path) -> bytes:
        if self.suffix == ".jpg" and self.parent.name == "frames":
            raise AssertionError(f"re-read frame {self}")
        return real_read(self)

    monkeypatch.setattr(Path, "read_bytes", guarded)
    storage.close_event(
        event,
        end_utc=start + 1,
        end_reason="no_motion",
        frames=2,
        pre_roll_frames=0,
        bad_frames_dropped=0,
    )
    monkeypatch.setattr(Path, "read_bytes", real_read)
    assert (event / "SHA256SUMS").read_text(encoding="utf-8") == _sums_from_disk(event)


def test_latest_replaced_atomically(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []
    real = os.replace

    def spy(src, dst) -> None:
        calls.append((str(src), str(dst)))
        real(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    storage = _storage(tmp_path, latest_jpeg_seconds=1)
    storage.write_latest("sentinel_a", b"one", 0)
    storage.write_latest("sentinel_a", b"two", 0.5)
    target = tmp_path / "sentinel_a" / "latest.jpg"
    assert target.read_bytes() == b"one"
    storage.write_latest("sentinel_a", b"three", 2)
    assert target.read_bytes() == b"three"
    assert calls[-1][1] == str(target)
    assert not list((tmp_path / "sentinel_a").glob(".latest*"))
    assert not list((tmp_path / "sentinel_a").glob("*.tmp"))
