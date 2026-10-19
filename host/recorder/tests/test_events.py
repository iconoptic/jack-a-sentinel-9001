from __future__ import annotations

from datetime import datetime, timezone

from sentinel_recorder.config import RecorderSettings, ScheduleSettings
from sentinel_recorder.events import EventRecorder

UTC = timezone.utc
ALLOWED = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


class FakeStorage:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def open_event(self, *, camera: str, start_utc: float, pre_roll_frames: int) -> int:
        self.events.append(
            {
                "camera": camera,
                "start": start_utc,
                "frames": [],
                "pre_roll_frames": pre_roll_frames,
                "reason": None,
                "end": None,
                "bad": 0,
                "frames_field": None,
            }
        )
        return len(self.events) - 1

    def write_frame(self, event: int, seq: int, ts: float, jpeg: bytes) -> None:
        self.events[event]["frames"].append((seq, ts, jpeg))

    def close_event(
        self,
        event: int,
        *,
        end_utc: float,
        end_reason: str,
        frames: int,
        pre_roll_frames: int,
        bad_frames_dropped: int,
    ) -> None:
        row = self.events[event]
        row["end"] = end_utc
        row["reason"] = end_reason
        row["frames_field"] = frames
        row["pre_roll_frames"] = pre_roll_frames
        row["bad"] = bad_frames_dropped


def _recorder(
    storage: FakeStorage,
    *,
    pre: float = 5,
    post: float = 30,
    limit: float = 900,
    schedule: ScheduleSettings | None = None,
) -> EventRecorder:
    settings = RecorderSettings(
        pre_roll_seconds=pre,
        post_roll_seconds=post,
        max_event_seconds=limit,
    )
    return EventRecorder("sentinel_a", settings, schedule or ScheduleSettings(enabled=False), storage)


def _times(storage: FakeStorage) -> list[float]:
    return [ts for event in storage.events for _seq, ts, _jpeg in event["frames"]]


def test_preroll_written_first_and_in_order() -> None:
    storage = FakeStorage()
    recorder = _recorder(storage, pre=5)
    recorder.on_frame(0, b"old", False, ALLOWED)
    for ts in (10, 11, 12, 13):
        recorder.on_frame(float(ts), f"{ts}".encode(), False, ALLOWED)
    recorder.on_frame(14, b"14", True, ALLOWED)
    assert len(storage.events) == 1
    frames = storage.events[0]["frames"]
    assert [ts for _seq, ts, _jpeg in frames] == [10, 11, 12, 13, 14]
    assert [jpeg for _seq, _ts, jpeg in frames] == [b"10", b"11", b"12", b"13", b"14"]
    assert storage.events[0]["pre_roll_frames"] == 4


def test_post_roll_closes() -> None:
    storage = FakeStorage()
    recorder = _recorder(storage, pre=0, post=10)
    recorder.on_frame(0, b"a", True, ALLOWED)
    recorder.on_frame(5, b"b", False, ALLOWED)
    assert storage.events[0]["reason"] is None
    recorder.on_frame(10, b"c", False, ALLOWED)
    assert storage.events[0]["reason"] == "no_motion"
    assert _times(storage) == [0, 5, 10]


def test_motion_during_post_roll_extends() -> None:
    storage = FakeStorage()
    recorder = _recorder(storage, pre=0, post=10)
    recorder.on_frame(0, b"a", True, ALLOWED)
    recorder.on_frame(5, b"b", False, ALLOWED)
    recorder.on_frame(9, b"c", True, ALLOWED)
    recorder.on_frame(18, b"d", False, ALLOWED)
    assert storage.events[0]["reason"] is None
    recorder.on_frame(19, b"e", False, ALLOWED)
    assert storage.events[0]["reason"] == "no_motion"
    assert _times(storage) == [0, 5, 9, 18, 19]


def test_max_length_splits_without_losing_frames() -> None:
    storage = FakeStorage()
    recorder = _recorder(storage, pre=5, post=100, limit=10)
    for ts in (0, 4, 8, 12, 16):
        recorder.on_frame(float(ts), str(ts).encode(), True, ALLOWED)
    recorder.on_disconnect(16)
    assert [event["reason"] for event in storage.events] == ["max_length", "camera_offline"]
    assert _times(storage) == [0, 4, 8, 12, 16]
    assert storage.events[1]["pre_roll_frames"] == 0


def test_no_event_opens_in_the_quiet_window() -> None:
    storage = FakeStorage()
    schedule = ScheduleSettings(enabled=True, timezone="UTC")
    recorder = _recorder(storage, schedule=schedule)
    quiet = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    recorder.on_frame(0, b"a", True, quiet)
    recorder.on_frame(1, b"b", True, quiet)
    assert storage.events == []


def test_event_running_at_monday_0600_finishes() -> None:
    storage = FakeStorage()
    schedule = ScheduleSettings(enabled=True, timezone="UTC")
    recorder = _recorder(storage, pre=0, post=3600, limit=9000, schedule=schedule)
    opened = datetime(2026, 10, 19, 5, 50, tzinfo=UTC)
    quiet = datetime(2026, 10, 19, 6, 0, tzinfo=UTC)
    still = datetime(2026, 10, 19, 6, 10, tzinfo=UTC)
    done = datetime(2026, 10, 19, 7, 10, tzinfo=UTC)
    recorder.on_frame(opened.timestamp(), b"a", True, opened)
    recorder.on_frame(quiet.timestamp(), b"b", True, quiet)
    recorder.on_frame(still.timestamp(), b"c", False, still)
    assert len(storage.events) == 1
    assert storage.events[0]["reason"] is None
    recorder.on_frame(done.timestamp(), b"d", False, done)
    assert storage.events[0]["reason"] == "no_motion"
    assert len(storage.events) == 1


def test_disconnect_closes_camera_offline() -> None:
    storage = FakeStorage()
    recorder = _recorder(storage, pre=0)
    recorder.on_frame(0, b"a", True, ALLOWED)
    recorder.on_disconnect(5)
    assert storage.events[0]["reason"] == "camera_offline"
    assert storage.events[0]["end"] == 5


def test_shutdown_closes_shutdown() -> None:
    storage = FakeStorage()
    recorder = _recorder(storage, pre=0)
    recorder.on_frame(0, b"a", True, ALLOWED)
    recorder.on_shutdown(3)
    assert storage.events[0]["reason"] == "shutdown"
