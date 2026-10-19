from __future__ import annotations

import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_DAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_TIME = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")
_SOURCES = ("stream", "snapshot")


@dataclass(frozen=True)
class Camera:
    frigate_name: str
    id: str
    static_ip: str


@dataclass(frozen=True)
class RecorderSettings:
    recordings_dir: Path = Path("/var/lib/sentinel/recordings")
    source: str = "stream"
    snapshot_fps: float = 5
    pre_roll_seconds: float = 5
    post_roll_seconds: float = 30
    max_event_seconds: float = 900
    latest_jpeg_seconds: float = 2
    retain_days: int = 30
    max_disk_gb: float = 100
    connect_timeout_seconds: float = 5
    read_timeout_seconds: float = 10


@dataclass(frozen=True)
class ScheduleSettings:
    enabled: bool = True
    timezone: str = "UTC"
    quiet_days: tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri")
    quiet_start: str = "06:00"
    quiet_end: str = "16:00"

    def quiet_minutes(self) -> tuple[int, int]:
        return _hhmm_minutes(self.quiet_start), _hhmm_minutes(self.quiet_end)


@dataclass(frozen=True)
class MotionSettings:
    analysis_width: int = 160
    pixel_threshold: int = 25
    min_area_percent: float = 1.0
    trigger_frames: int = 2
    background_alpha: float = 0.05
    masks: tuple[tuple[float, float, float, float], ...] = ()


@dataclass(frozen=True)
class Config:
    recorder: RecorderSettings
    schedule: ScheduleSettings
    motion: MotionSettings
    cameras: tuple[Camera, ...]


def resolve_config_path(arg: str | None = None) -> Path:
    if arg:
        return Path(arg)
    env = os.environ.get("SENTINEL_RECORDER_CONFIG")
    if env:
        return Path(env)
    return Path("/etc/sentinel/recorder.toml")


def load_config(path: Path | None = None) -> Config:
    if path is None:
        path = resolve_config_path(None)
    if not path.is_file():
        raise FileNotFoundError(f"config not found: {path}")
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    return config_from_mapping(raw)


def config_from_mapping(raw: dict) -> Config:
    recorder_raw = raw.get("recorder") or {}
    schedule_raw = raw.get("schedule") or {}
    motion_raw = raw.get("motion") or {}
    recorder = RecorderSettings(
        recordings_dir=Path(recorder_raw.get("recordings_dir", "/var/lib/sentinel/recordings")),
        source=str(recorder_raw.get("source", "stream")),
        snapshot_fps=float(recorder_raw.get("snapshot_fps", 5)),
        pre_roll_seconds=float(recorder_raw.get("pre_roll_seconds", 5)),
        post_roll_seconds=float(recorder_raw.get("post_roll_seconds", 30)),
        max_event_seconds=float(recorder_raw.get("max_event_seconds", 900)),
        latest_jpeg_seconds=float(recorder_raw.get("latest_jpeg_seconds", 2)),
        retain_days=int(recorder_raw.get("retain_days", 30)),
        max_disk_gb=float(recorder_raw.get("max_disk_gb", 100)),
        connect_timeout_seconds=float(recorder_raw.get("connect_timeout_seconds", 5)),
        read_timeout_seconds=float(recorder_raw.get("read_timeout_seconds", 10)),
    )
    quiet_days = tuple(
        str(day).lower() for day in schedule_raw.get("quiet_days", ["mon", "tue", "wed", "thu", "fri"])
    )
    schedule = ScheduleSettings(
        enabled=bool(schedule_raw.get("enabled", True)),
        timezone=str(schedule_raw.get("timezone", "UTC")),
        quiet_days=quiet_days,
        quiet_start=str(schedule_raw.get("quiet_start", "06:00")),
        quiet_end=str(schedule_raw.get("quiet_end", "16:00")),
    )
    motion = MotionSettings(
        analysis_width=int(motion_raw.get("analysis_width", 160)),
        pixel_threshold=int(motion_raw.get("pixel_threshold", 25)),
        min_area_percent=float(motion_raw.get("min_area_percent", 1.0)),
        trigger_frames=int(motion_raw.get("trigger_frames", 2)),
        background_alpha=float(motion_raw.get("background_alpha", 0.05)),
        masks=_parse_masks(motion_raw.get("masks", [])),
    )
    cameras_raw = raw.get("cameras")
    if not cameras_raw:
        raise ValueError("config needs at least one [[cameras]] table")
    cameras = tuple(
        Camera(
            frigate_name=str(item["frigate_name"]),
            id=str(item["id"]),
            static_ip=str(item["static_ip"]),
        )
        for item in cameras_raw
    )
    _validate(recorder, schedule, motion, cameras)
    return Config(recorder=recorder, schedule=schedule, motion=motion, cameras=cameras)


def _validate(
    recorder: RecorderSettings,
    schedule: ScheduleSettings,
    motion: MotionSettings,
    cameras: tuple[Camera, ...],
) -> None:
    if recorder.source not in _SOURCES:
        raise ValueError(f"recorder.source must be 'stream' or 'snapshot', got {recorder.source!r}")
    if recorder.snapshot_fps <= 0:
        raise ValueError("snapshot_fps must be positive")
    if recorder.pre_roll_seconds < 0 or recorder.post_roll_seconds < 0:
        raise ValueError("pre_roll_seconds and post_roll_seconds must be >= 0")
    if recorder.max_event_seconds <= 0:
        raise ValueError("max_event_seconds must be positive")
    if recorder.retain_days < 0 or recorder.max_disk_gb < 0:
        raise ValueError("retain_days and max_disk_gb must be >= 0")
    if recorder.connect_timeout_seconds <= 0 or recorder.read_timeout_seconds <= 0:
        raise ValueError("timeouts must be positive")
    _check_time(schedule.quiet_start, "quiet_start")
    _check_time(schedule.quiet_end, "quiet_end")
    if _hhmm_minutes(schedule.quiet_start) >= _hhmm_minutes(schedule.quiet_end):
        raise ValueError("quiet_start must be earlier than quiet_end")
    for day in schedule.quiet_days:
        if day not in _DAYS:
            raise ValueError(f"unknown day {day!r}")
    try:
        ZoneInfo(schedule.timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown timezone {schedule.timezone!r}") from exc
    if motion.analysis_width < 1:
        raise ValueError("analysis_width must be >= 1")
    if not 0 <= motion.pixel_threshold <= 255:
        raise ValueError("pixel_threshold must be between 0 and 255")
    if motion.min_area_percent < 0:
        raise ValueError("min_area_percent must be >= 0")
    if motion.trigger_frames < 1:
        raise ValueError("trigger_frames must be >= 1")
    if not 0 <= motion.background_alpha <= 1:
        raise ValueError("background_alpha must be between 0 and 1")
    seen: set[str] = set()
    for camera in cameras:
        if not camera.id or not camera.frigate_name or not camera.static_ip:
            raise ValueError("each camera needs frigate_name, id, and static_ip")
        if camera.id in seen:
            raise ValueError(f"duplicate camera id {camera.id!r}")
        seen.add(camera.id)


def _parse_masks(raw: object) -> tuple[tuple[float, float, float, float], ...]:
    if not isinstance(raw, list):
        raise ValueError("motion.masks must be a list of [x0, y0, x1, y1] fractions")
    masks: list[tuple[float, float, float, float]] = []
    for item in raw:
        if not isinstance(item, (list, tuple)) or len(item) != 4:
            raise ValueError("each mask must be [x0, y0, x1, y1]")
        try:
            x0, y0, x1, y1 = (float(value) for value in item)
        except (TypeError, ValueError) as exc:
            raise ValueError("mask values must be numbers") from exc
        if not (0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0):
            raise ValueError(f"mask {[x0, y0, x1, y1]} is outside the frame")
        masks.append((x0, y0, x1, y1))
    return tuple(masks)


def _check_time(value: str, label: str) -> None:
    if _TIME.fullmatch(value) is None:
        raise ValueError(f"{label} must be HH:MM, got {value!r}")


def _hhmm_minutes(value: str) -> int:
    hours, minutes = value.split(":")
    return int(hours) * 60 + int(minutes)
