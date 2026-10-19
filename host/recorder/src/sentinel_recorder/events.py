from __future__ import annotations

from collections import deque
from datetime import datetime
from typing import Any, Protocol

from sentinel_recorder.config import RecorderSettings, ScheduleSettings
from sentinel_recorder.schedule import is_allowed


class EventStore(Protocol):
    def open_event(self, *, camera: str, start_utc: float, pre_roll_frames: int) -> Any: ...

    def write_frame(self, event: Any, seq: int, ts: float, jpeg: bytes) -> None: ...

    def close_event(
        self,
        event: Any,
        *,
        end_utc: float,
        end_reason: str,
        frames: int,
        pre_roll_frames: int,
        bad_frames_dropped: int,
    ) -> None: ...


class EventRecorder:
    """Pre-roll ring and the recording state machine. No clock reads and no I/O."""

    def __init__(
        self,
        camera: str,
        recorder: RecorderSettings,
        schedule: ScheduleSettings,
        storage: EventStore,
    ) -> None:
        self.camera = camera
        self.recorder = recorder
        self.schedule = schedule
        self.storage = storage
        self.state = "watching"
        self.ring: deque[tuple[float, bytes]] = deque()
        self.event: Any = None
        self.start_ts = 0.0
        self.last_motion_ts = 0.0
        self.frame_count = 0
        self.pre_roll_frames = 0
        self.bad_frames = 0
        self._pending_bad = 0
        self._seq = 0

    @property
    def state_name(self) -> str:
        if self.state == "watching":
            return "watching"
        return "recording"

    def note_bad_frame(self) -> None:
        if self.state == "recording":
            self.bad_frames += 1
        elif self.state == "pending":
            self._pending_bad += 1

    def on_frame(self, ts: float, jpeg: bytes, is_motion: bool, now: datetime) -> None:
        if self.state == "pending":
            self._open(ts, 0)
            if is_motion:
                self.last_motion_ts = ts
            self._write(ts, jpeg)
            self._after_write(ts, is_motion, now)
            return

        if self.state == "watching":
            if is_motion and is_allowed(now, self.schedule):
                pre = self._take_preroll(ts)
                self._open(pre[0][0] if pre else ts, len(pre))
                for old_ts, old_jpeg in pre:
                    self._write(old_ts, old_jpeg)
                self._write(ts, jpeg)
                self.last_motion_ts = ts
                self._after_write(ts, True, now)
            else:
                self.ring.append((ts, jpeg))
                self._trim(ts)
            return

        self._write(ts, jpeg)
        if is_motion:
            self.last_motion_ts = ts
        self._after_write(ts, is_motion, now)

    def on_disconnect(self, ts: float) -> None:
        self._end(ts, "camera_offline")

    def on_shutdown(self, ts: float) -> None:
        self._end(ts, "shutdown")

    def _take_preroll(self, ts: float) -> list[tuple[float, bytes]]:
        cutoff = ts - self.recorder.pre_roll_seconds
        kept = [(frame_ts, jpeg) for frame_ts, jpeg in self.ring if frame_ts >= cutoff]
        self.ring.clear()
        return kept

    def _trim(self, ts: float) -> None:
        cutoff = ts - self.recorder.pre_roll_seconds
        while self.ring and self.ring[0][0] < cutoff:
            self.ring.popleft()

    def _open(self, start_ts: float, pre_roll_frames: int) -> None:
        self.start_ts = start_ts
        self.frame_count = 0
        self.pre_roll_frames = pre_roll_frames
        self.bad_frames = self._pending_bad
        self._pending_bad = 0
        self._seq = 0
        self.state = "recording"
        self.event = self.storage.open_event(
            camera=self.camera,
            start_utc=start_ts,
            pre_roll_frames=pre_roll_frames,
        )

    def _write(self, ts: float, jpeg: bytes) -> None:
        self._seq += 1
        self.frame_count += 1
        self.storage.write_frame(self.event, self._seq, ts, jpeg)

    def _after_write(self, ts: float, is_motion: bool, now: datetime) -> None:
        if self.state != "recording":
            return
        if ts - self.start_ts >= self.recorder.max_event_seconds:
            self._close(ts, "max_length")
            if is_motion and is_allowed(now, self.schedule):
                self.last_motion_ts = ts
                self.state = "pending"
            return
        if not is_motion and ts - self.last_motion_ts >= self.recorder.post_roll_seconds:
            self._close(ts, "no_motion")

    def _close(self, end_ts: float, reason: str) -> None:
        self.storage.close_event(
            self.event,
            end_utc=end_ts,
            end_reason=reason,
            frames=self.frame_count,
            pre_roll_frames=self.pre_roll_frames,
            bad_frames_dropped=self.bad_frames,
        )
        self.event = None
        self.state = "watching"
        self.ring.clear()

    def _end(self, ts: float, reason: str) -> None:
        if self.state == "recording" and self.event is not None:
            self._close(ts, reason)
        else:
            self.state = "watching"
            self._pending_bad = 0
