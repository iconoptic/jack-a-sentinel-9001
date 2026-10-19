"""Render /etc/sentinel/recorder.toml and recorder.env for simple mode.

The template is host/recorder/config.toml (Prompt A's package). This module
replaces [[cameras]] and schedule.timezone, and writes only the selected
cameras' stream tokens. It does not import the recorder package.
"""

from __future__ import annotations

import tomllib
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sentinel_provision.cameras import CAMERAS, CameraSpec

# Same characters render_frigate_config rejects: they break a URL or an env line.
_UNSAFE_TOKEN_CHARS = "#{}&\n\r \"'"

_RECORDER_KEYS = (
    "recordings_dir",
    "source",
    "snapshot_fps",
    "pre_roll_seconds",
    "post_roll_seconds",
    "max_event_seconds",
    "latest_jpeg_seconds",
    "retain_days",
    "max_disk_gb",
    "connect_timeout_seconds",
    "read_timeout_seconds",
)
_SCHEDULE_KEYS = ("enabled", "timezone", "quiet_days", "quiet_start", "quiet_end")
_MOTION_KEYS = (
    "analysis_width",
    "pixel_threshold",
    "min_area_percent",
    "trigger_frames",
    "background_alpha",
    "masks",
)
_CAMERA_KEYS = ("frigate_name", "id", "static_ip")


def render_recorder_config(
    template: str,
    camera_names: list[str],
    *,
    timezone: str,
    ignore_schedule: bool = False,
) -> str:
    """Template text in, installed recorder.toml text out. Flat schema only."""
    if not camera_names:
        raise ValueError("render-recorder needs at least one camera")
    try:
        ZoneInfo(timezone)
    except ZoneInfoNotFoundError as exc:
        raise ValueError(f"unknown timezone {timezone!r}") from exc

    data = tomllib.loads(template)
    recorder = _section(data, "recorder")
    schedule = _section(data, "schedule")
    motion = _section(data, "motion")
    _require_keys("recorder", recorder, _RECORDER_KEYS)
    _require_keys("schedule", schedule, _SCHEDULE_KEYS)
    _require_keys("motion", motion, _MOTION_KEYS)

    schedule["timezone"] = timezone
    if ignore_schedule:
        schedule["enabled"] = False

    cameras: list[dict[str, str]] = []
    for name in camera_names:
        cam = CAMERAS[name]
        cameras.append(
            {
                "frigate_name": cam.frigate_name,
                "id": cam.camera_id,
                "static_ip": cam.static_ip,
            }
        )

    parts = [
        "# Rendered by sentinel-provision render-recorder. Re-run the installer to change it.",
        "",
        _emit_table("recorder", recorder),
        _emit_table("schedule", schedule),
        _emit_table("motion", motion),
    ]
    for cam in cameras:
        parts.append(_emit_camera(cam))
    return "\n".join(parts).rstrip() + "\n"


def render_recorder_env(cameras: list[CameraSpec], tokens_by_id: dict[str, str]) -> str:
    """Only SENTINEL_STREAM_TOKEN_<ID>= lines, one per selected camera."""
    lines: list[str] = []
    for cam in cameras:
        key = f"SENTINEL_STREAM_TOKEN_{cam.camera_id.upper()}"
        try:
            token = tokens_by_id[cam.camera_id]
        except KeyError as exc:
            raise ValueError(f"missing stream token for camera {cam.camera_id}") from exc
        if not token or any(ch in token for ch in _UNSAFE_TOKEN_CHARS):
            raise ValueError(f"{key} is empty or has characters that are not allowed in a stream token")
        lines.append(f"{key}={token}")
    return "\n".join(lines) + "\n"


def _section(data: dict, name: str) -> dict:
    section = data.get(name)
    if not isinstance(section, dict):
        raise ValueError(f"recorder template is missing [{name}]")
    return section


def _require_keys(name: str, section: dict, keys: tuple[str, ...]) -> None:
    missing = [key for key in keys if key not in section]
    if missing:
        raise ValueError(f"[{name}] is missing {', '.join(missing)}")


def _emit_table(name: str, section: dict) -> str:
    lines = [f"[{name}]"]
    for key, value in section.items():
        lines.append(f"{key} = {_format_toml(value)}")
    return "\n".join(lines)


def _emit_camera(cam: dict[str, str]) -> str:
    lines = ["[[cameras]]"]
    for key in _CAMERA_KEYS:
        lines.append(f"{key} = {_format_toml(cam[key])}")
    return "\n".join(lines)


def _format_toml(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        text = format(value, ".12g")
        if "e" not in text and "." not in text:
            text += ".0"
        return text
    if isinstance(value, str):
        escaped = (
            value.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\r", "\\r")
            .replace("\t", "\\t")
        )
        return f'"{escaped}"'
    if isinstance(value, list):
        return "[" + ", ".join(_format_toml(item) for item in value) + "]"
    raise ValueError("nested tables are not part of the recorder schema")
