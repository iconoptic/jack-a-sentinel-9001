from pathlib import Path

from sentinel_provision.cameras import CAMERAS
from sentinel_provision.credentials import (
    ensure_mqtt_user_line,
    load_or_create_camera_secrets,
    upsert_frigate_stream_token,
)


def test_camera_secrets_idempotent(tmp_path: Path) -> None:
    cam = CAMERAS["sentinel_a"]
    first = load_or_create_camera_secrets(tmp_path, cam)
    second = load_or_create_camera_secrets(tmp_path, cam)
    assert first.mqtt_password == second.mqtt_password
    assert first.stream_token == second.stream_token


def test_mqtt_users_append_once(tmp_path: Path) -> None:
    users = tmp_path / "users"
    assert ensure_mqtt_user_line(users, "cam_b", "pass1")
    assert ensure_mqtt_user_line(users, "cam_b", "pass2") is False
    text = users.read_text()
    assert text.count("cam_b:") == 1
    assert "pass1" in text


def test_frigate_env_token_upsert(tmp_path: Path) -> None:
    env = tmp_path / "frigate.env"
    env.write_text("FRIGATE_MQTT_HOST=127.0.0.1\n")
    assert upsert_frigate_stream_token(env, "FRIGATE_STREAM_TOKEN_B", "abc123")
    assert "FRIGATE_STREAM_TOKEN_B=abc123" in env.read_text()
    assert upsert_frigate_stream_token(env, "FRIGATE_STREAM_TOKEN_B", "abc123") is False
