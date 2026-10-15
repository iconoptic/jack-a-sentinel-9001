import json
from pathlib import Path

from sentinel_provision.bind_payload import BIND_JSON_KEYS, bind_payload_json, build_bind_payload
from sentinel_provision.cameras import CAMERAS
from sentinel_provision.frigate_config import ensure_frigate_camera
from sentinel_provision.mosquitto_config import ensure_acl_block

MINIMAL_FRIGATE_YML = """
go2rtc:
  streams:
    sentinel_a: "ffmpeg:http://10.77.0.11/stream?token={FRIGATE_STREAM_TOKEN_A}#video=h264#hardware"
  api:
    listen: "127.0.0.1:1984"

cameras:
  sentinel_a:
    detect:
      enabled: true

networking:
  listen:
    internal: 127.0.0.1:5000
"""


def test_bind_json_golden_shape() -> None:
    cam = CAMERAS["sentinel_a"]
    payload = build_bind_payload(
        cam,
        mqtt_password="secret",
        stream_token="tok",
        wifi_bssid="aa:bb:cc:dd:ee:ff",
        wifi_channel=6,
    )
    raw = bind_payload_json(payload)
    parsed = json.loads(raw)
    assert list(parsed.keys()) == list(BIND_JSON_KEYS)
    assert "mqtt_ca_pem" not in parsed
    assert parsed["host_id"] == "fedora-cubicle-1"
    assert parsed["camera_id"] == "a"
    assert parsed["mqtt_port"] == 1883
    assert parsed["wifi_channel"] == 6


def test_acl_block_idempotent(tmp_path: Path) -> None:
    cam = CAMERAS["sentinel_b"]
    acl = tmp_path / "acl"
    assert ensure_acl_block(acl, cam) is True
    assert "user cam_b" in acl.read_text()
    assert ensure_acl_block(acl, cam) is False


def test_frigate_patch_adds_camera(tmp_path: Path) -> None:
    cfg = tmp_path / "config.yml"
    cfg.write_text(MINIMAL_FRIGATE_YML)
    cam = CAMERAS["sentinel_b"]
    assert ensure_frigate_camera(
        cfg, cam, token_placeholder="{FRIGATE_STREAM_TOKEN_B}", generated_dir=tmp_path / "gen"
    )
    text = cfg.read_text()
    assert "sentinel_b:" in text
    assert "10.77.0.12" in text
    assert "{FRIGATE_STREAM_TOKEN_B}" in text
    assert ensure_frigate_camera(cfg, cam, token_placeholder="{FRIGATE_STREAM_TOKEN_B}") is False
