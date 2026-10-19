"""render-recorder: selected cameras, timezone, schedule flag, private files."""

import stat
import tomllib
from pathlib import Path

import pytest

from sentinel_provision.__main__ import build_parser
from sentinel_provision.cameras import CAMERAS
from sentinel_provision.credentials import write_private
from sentinel_provision.recorder_config import render_recorder_config, render_recorder_env

TEMPLATE = """\
[recorder]
recordings_dir = "/var/lib/sentinel/recordings"
source = "stream"
snapshot_fps = 5
pre_roll_seconds = 5
post_roll_seconds = 30
max_event_seconds = 900
latest_jpeg_seconds = 2
retain_days = 30
max_disk_gb = 100
connect_timeout_seconds = 5
read_timeout_seconds = 10

[schedule]
enabled = true
timezone = "UTC"
quiet_days = ["mon", "tue", "wed", "thu", "fri"]
quiet_start = "06:00"
quiet_end = "16:00"

[motion]
analysis_width = 160
pixel_threshold = 25
min_area_percent = 1.0
trigger_frames = 2
background_alpha = 0.05
masks = []

[[cameras]]
frigate_name = "sentinel_a"
id = "a"
static_ip = "10.77.0.11"
"""

RECORDER_KEYS = {
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
}
SCHEDULE_KEYS = {"enabled", "timezone", "quiet_days", "quiet_start", "quiet_end"}
MOTION_KEYS = {
    "analysis_width",
    "pixel_threshold",
    "min_area_percent",
    "trigger_frames",
    "background_alpha",
    "masks",
}
TOKENS = {"a": "tokA-unique", "b": "tokB-unique", "c": "tokC-unique"}


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _write_camera_env(secrets: Path, camera_id: str, token: str) -> None:
    write_private(
        secrets / "cameras" / f"{camera_id}.env",
        f"MQTT_USERNAME=cam_{camera_id}\nMQTT_PASSWORD=pw-{camera_id}\nSTREAM_TOKEN={token}\n",
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    (root / "host" / "recorder").mkdir(parents=True)
    (root / "host" / "recorder" / "config.toml").write_text(TEMPLATE)
    for camera_id, token in TOKENS.items():
        _write_camera_env(root / "secrets", camera_id, token)
    return root


def _invoke(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


def _render(repo: Path, tmp_path: Path, *extra: str) -> tuple[dict, str]:
    out = tmp_path / "recorder.toml"
    env = tmp_path / "recorder.env"
    rc = _invoke(
        [
            "--repo-root",
            str(repo),
            "render-recorder",
            "--timezone",
            "America/Chicago",
            "--out",
            str(out),
            "--env-out",
            str(env),
            *extra,
        ]
    )
    assert rc == 0
    assert _mode(out) == 0o600
    assert _mode(env) == 0o600
    text = out.read_text()
    return tomllib.loads(text), env.read_text()


def _assert_schema(data: dict) -> None:
    assert set(data["recorder"]) == RECORDER_KEYS
    assert set(data["schedule"]) == SCHEDULE_KEYS
    assert set(data["motion"]) == MOTION_KEYS
    assert data["recorder"]["recordings_dir"] == "/var/lib/sentinel/recordings"
    assert data["recorder"]["source"] == "stream"
    assert data["recorder"]["pre_roll_seconds"] == 5
    assert data["schedule"]["quiet_days"] == ["mon", "tue", "wed", "thu", "fri"]
    assert data["schedule"]["quiet_start"] == "06:00"
    assert data["schedule"]["quiet_end"] == "16:00"
    assert data["schedule"]["timezone"] == "America/Chicago"
    assert data["motion"]["pixel_threshold"] == 25
    assert data["motion"]["min_area_percent"] == 1.0
    assert data["motion"]["background_alpha"] == 0.05
    assert data["motion"]["masks"] == []
    for cam in data["cameras"]:
        assert set(cam) == {"frigate_name", "id", "static_ip"}


@pytest.mark.parametrize("camera_id", ["a", "b"])
def test_one_camera_replaces_the_template_table(repo: Path, tmp_path: Path, camera_id: str) -> None:
    data, env = _render(repo, tmp_path, "--cameras", camera_id)
    _assert_schema(data)
    assert data["schedule"]["enabled"] is True
    spec = CAMERAS[f"sentinel_{camera_id}"]
    assert data["cameras"] == [
        {"frigate_name": spec.frigate_name, "id": spec.camera_id, "static_ip": spec.static_ip}
    ]
    assert env == f"SENTINEL_STREAM_TOKEN_{camera_id.upper()}={TOKENS[camera_id]}\n"
    for other, token in TOKENS.items():
        if other != camera_id:
            assert token not in env
            assert f"SENTINEL_STREAM_TOKEN_{other.upper()}" not in env


def test_three_cameras_and_timezone(repo: Path, tmp_path: Path) -> None:
    data, env = _render(repo, tmp_path, "--cameras", "a,b,c")
    _assert_schema(data)
    assert data["cameras"] == [
        {
            "frigate_name": cam.frigate_name,
            "id": cam.camera_id,
            "static_ip": cam.static_ip,
        }
        for cam in (CAMERAS["sentinel_a"], CAMERAS["sentinel_b"], CAMERAS["sentinel_c"])
    ]
    assert env == (
        "SENTINEL_STREAM_TOKEN_A=tokA-unique\n"
        "SENTINEL_STREAM_TOKEN_B=tokB-unique\n"
        "SENTINEL_STREAM_TOKEN_C=tokC-unique\n"
    )
    again = render_recorder_config(
        (repo / "host" / "recorder" / "config.toml").read_text(),
        ["sentinel_a", "sentinel_b", "sentinel_c"],
        timezone="America/Chicago",
    )
    assert tomllib.loads(again) == data


def test_ignore_schedule_is_not_a_timezone_change(repo: Path, tmp_path: Path) -> None:
    data, env = _render(repo, tmp_path, "--cameras", "a", "--ignore-schedule")
    _assert_schema(data)
    assert data["schedule"]["enabled"] is False
    assert data["schedule"]["quiet_start"] == "06:00"
    assert env == "SENTINEL_STREAM_TOKEN_A=tokA-unique\n"


def test_unsafe_token_is_refused(repo: Path, tmp_path: Path) -> None:
    _write_camera_env(repo / "secrets", "a", "bad token")
    cam = CAMERAS["sentinel_a"]
    with pytest.raises(ValueError, match="SENTINEL_STREAM_TOKEN_A") as raised:
        render_recorder_env([cam], {"a": "bad token"})
    assert "bad token" not in str(raised.value)

    out = tmp_path / "recorder.toml"
    env = tmp_path / "recorder.env"
    with pytest.raises(SystemExit, match="SENTINEL_STREAM_TOKEN_A") as exited:
        _invoke(
            [
                "--repo-root",
                str(repo),
                "render-recorder",
                "--cameras",
                "a",
                "--timezone",
                "America/Chicago",
                "--out",
                str(out),
                "--env-out",
                str(env),
            ]
        )
    assert "bad token" not in str(exited.value)
    assert not out.exists()
    assert not env.exists()
