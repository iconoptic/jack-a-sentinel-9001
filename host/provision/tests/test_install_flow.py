"""One-click install path: secret generation, Frigate rendering, and the NVS bind image."""

import csv
import io
import os
import re
import stat
from pathlib import Path

import pytest

from sentinel_provision.ap_env import ensure_ap_env, load_ap_env, read_ap_env_raw, update_ap_env
from sentinel_provision.bind_payload import build_bind_payload
from sentinel_provision.cameras import CAMERAS
from sentinel_provision.credentials import (
    load_camera_secrets,
    parse_env_file,
    read_users,
)
from sentinel_provision.frigate_config import add_camera_to_text, render_frigate_config
from sentinel_provision.init_secrets import init_secrets
from sentinel_provision.nvs_image import bind_nvs_csv

REPO = Path(__file__).resolve().parents[3]
TEMPLATE = (REPO / "host" / "frigate" / "config.yml").read_text()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    (tmp_path / "host" / "mosquitto").mkdir(parents=True)
    (tmp_path / "host" / "mosquitto" / "acl.example").write_text(
        (REPO / "host" / "mosquitto" / "acl.example").read_text()
    )
    return tmp_path


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_init_generates_everything_consistently(repo: Path) -> None:
    secrets = repo / "secrets"
    init_secrets(secrets, repo)

    ap = read_ap_env_raw(secrets / "ap.env")
    assert re.fullmatch(r"ap[0-9a-f]{6}", ap["SSID"])
    assert "sentinel" not in ap["SSID"].lower()
    assert re.fullmatch(r"[0-9a-f]{32}", ap["PSK"])
    assert ap["CHANNEL"] == "" and ap["WIFI_BSSID"] == "" and ap["WIFI_IFACE"] == ""

    users = read_users(secrets / "mosquitto" / "users")
    frigate_env = parse_env_file(secrets / "frigate.env")
    assert set(users) == {"frigate", "controller", "cam_a", "cam_b", "cam_c"}
    assert len(set(users.values())) == 5, "every account gets its own password"
    assert frigate_env["FRIGATE_MQTT_PASSWORD"] == users["frigate"]
    assert (secrets / "mosquitto" / "controller.password").read_text() == users["controller"]

    tokens = set()
    for cam in CAMERAS.values():
        creds = load_camera_secrets(secrets, cam)
        # the bind payload password must be the one mosquitto will accept
        assert creds.mqtt_password == users[cam.mqtt_username]
        assert frigate_env[cam.stream_token_env] == creds.stream_token
        tokens.add(creds.stream_token)
    assert len(tokens) == 3

    acl = (secrets / "mosquitto" / "acl").read_text()
    for cid in "abc":
        assert re.search(rf"^user cam_{cid}$", acl, re.M)
        assert f"topic write sentinel/{cid}/#" in acl


def test_init_is_idempotent_and_private(repo: Path) -> None:
    secrets = repo / "secrets"
    init_secrets(secrets, repo)
    snapshot = {p: p.read_text() for p in secrets.rglob("*") if p.is_file()}
    second = init_secrets(secrets, repo)
    assert {p: p.read_text() for p in secrets.rglob("*") if p.is_file()} == snapshot
    assert second.created == []

    for p in secrets.rglob("*"):
        if p.is_file():
            assert _mode(p) == 0o600, p
        else:
            assert _mode(p) == 0o700, p


def test_init_adopts_secrets_written_by_the_old_generator(repo: Path) -> None:
    """Old generate-secrets.sh made cam_a's password in users but no cameras/a.env."""
    secrets = repo / "secrets"
    (secrets / "mosquitto").mkdir(parents=True)
    (secrets / "mosquitto" / "users").write_text("frigate:fp\ncam_a:legacy-pass\ncontroller:cp\n")
    (secrets / "frigate.env").write_text(
        "FRIGATE_MQTT_HOST=127.0.0.1\nFRIGATE_MQTT_USER=frigate\n"
        "FRIGATE_MQTT_PASSWORD=fp\nFRIGATE_STREAM_TOKEN_A=legacy-token\n"
    )
    init_secrets(secrets, repo)
    a = load_camera_secrets(secrets, CAMERAS["sentinel_a"])
    assert (a.mqtt_password, a.stream_token) == ("legacy-pass", "legacy-token")
    users = read_users(secrets / "mosquitto" / "users")
    assert users["cam_a"] == "legacy-pass" and users["frigate"] == "fp"


def test_ap_env_update_preserves_and_validates(tmp_path: Path) -> None:
    path = tmp_path / "ap.env"
    ensure_ap_env(path)
    before = read_ap_env_raw(path)
    assert update_ap_env(path, {"CHANNEL": "6", "WIFI_IFACE": "wlp3s0", "WIFI_BSSID": "aa:bb:cc:dd:ee:01"})
    after = read_ap_env_raw(path)
    assert after["SSID"] == before["SSID"] and after["PSK"] == before["PSK"]
    assert not update_ap_env(path, {"CHANNEL": "6"})
    settings = load_ap_env(path, require_bssid=True)
    assert (settings.channel, settings.bssid) == (6, "aa:bb:cc:dd:ee:01")
    with pytest.raises(ValueError):
        update_ap_env(path, {"NOPE": "x"})


def test_ap_env_requires_bssid_when_asked(tmp_path: Path) -> None:
    path = tmp_path / "ap.env"
    ensure_ap_env(path)
    update_ap_env(path, {"CHANNEL": "11"})
    assert load_ap_env(path).bssid is None
    with pytest.raises(SystemExit, match="WIFI_BSSID"):
        load_ap_env(path, require_bssid=True)


def test_render_frigate_adds_all_cameras_as_valid_structure() -> None:
    tokens = {c.stream_token_env: f"tok{c.camera_id}" for c in CAMERAS.values()}
    out = render_frigate_config(TEMPLATE, list(CAMERAS), tokens)

    for cam in CAMERAS.values():
        # exactly one go2rtc stream line, on its own line, with the token filled in
        stream = re.findall(rf'^    {cam.frigate_name}: "(.*)"$', out, re.M)
        assert stream == [f"ffmpeg:http://{cam.static_ip}/stream?token=tok{cam.camera_id}#video=h264#hardware"]
        # exactly one camera block at top-level cameras:
        assert len(re.findall(rf"^  {cam.frigate_name}:$", out, re.M)) == 1
        assert f"rtsp://127.0.0.1:8554/{cam.frigate_name}" in out
    assert "{FRIGATE_STREAM_TOKEN" not in out
    assert "{FRIGATE_MQTT_PASSWORD}" in out, "MQTT placeholders stay for Frigate"
    # section order intact: cameras block ends before networking
    assert out.index("sentinel_c:\n    ffmpeg") < out.index("\nnetworking:")
    assert out.rstrip().endswith("external: 127.0.0.1:8971")


def test_render_is_idempotent_and_rejects_unsafe_tokens() -> None:
    once = render_frigate_config(TEMPLATE, ["sentinel_b"])
    text, changed = add_camera_to_text(once, CAMERAS["sentinel_b"], token_placeholder="{FRIGATE_STREAM_TOKEN_B}")
    assert not changed and text == once
    with pytest.raises(ValueError):
        render_frigate_config(TEMPLATE, ["sentinel_a"], {"FRIGATE_STREAM_TOKEN_A": "bad token"})


def test_nvs_csv_matches_firmware_keys() -> None:
    cam = CAMERAS["sentinel_b"]
    payload = build_bind_payload(
        cam,
        mqtt_password="mp",
        stream_token="st",
        wifi_bssid="AA:BB:CC:DD:EE:01",
        wifi_channel=11,
    )
    rows = list(csv.reader(io.StringIO(bind_nvs_csv(payload, wifi_ssid="ap1a2b3c", wifi_psk="0" * 32))))
    assert rows[0] == ["key", "type", "encoding", "value"]
    assert rows[1] == ["bind", "namespace", "", ""]
    got = {r[0]: (r[2], r[3]) for r in rows[2:]}
    # Names read by firmware/sentinel/components/sentinel_bind/bind_nvs.c
    assert got == {
        "bound": ("u8", "1"),
        "host_id": ("string", "fedora-cubicle-1"),
        "camera_id": ("string", "b"),
        "static_ip": ("string", "10.77.0.12"),
        "gateway": ("string", "10.77.0.1"),
        "netmask": ("string", "255.255.255.0"),
        "wifi_bssid": ("string", "aa:bb:cc:dd:ee:01"),
        "mqtt_broker": ("string", "10.77.0.1"),
        "mqtt_user": ("string", "cam_b"),
        "mqtt_pass": ("string", "mp"),
        "stream_tok": ("string", "st"),
        "wifi_ssid": ("string", "ap1a2b3c"),
        "wifi_psk": ("string", "0" * 32),
        "wifi_ch": ("u8", "11"),
        "mqtt_port": ("u16", "1883"),
    }


def test_nvs_keys_in_sync_with_firmware_source() -> None:
    """Guard against renaming a key on one side only."""
    src = (REPO / "firmware/sentinel/components/sentinel_bind/bind_nvs.c").read_text()
    firmware_keys = set(re.findall(r'(?:LOAD_STR|SAVE_STR)\("([a-z_]+)"', src))
    firmware_keys |= set(re.findall(r'nvs_(?:get|set)_u(?:8|16)\(h, "([a-z_]+)"', src))
    firmware_keys.add("bound")
    cam = CAMERAS["sentinel_a"]
    payload = build_bind_payload(
        cam, mqtt_password="m", stream_token="s", wifi_bssid="aa:bb:cc:dd:ee:ff", wifi_channel=1
    )
    rows = list(csv.reader(io.StringIO(bind_nvs_csv(payload, wifi_ssid="x", wifi_psk="y" * 8))))
    assert {r[0] for r in rows[2:]} == firmware_keys


@pytest.mark.parametrize("ssid,psk", [("", "0" * 32), ("x" * 33, "0" * 32), ("ok", "short"), ("ok", "p" * 64)])
def test_nvs_csv_rejects_bad_wifi_values(ssid: str, psk: str) -> None:
    payload = build_bind_payload(
        CAMERAS["sentinel_a"], mqtt_password="m", stream_token="s", wifi_bssid="aa:bb:cc:dd:ee:ff", wifi_channel=1
    )
    with pytest.raises(ValueError):
        bind_nvs_csv(payload, wifi_ssid=ssid, wifi_psk=psk)


def test_load_camera_secrets_is_read_only(tmp_path: Path) -> None:
    with pytest.raises(SystemExit, match="Missing"):
        load_camera_secrets(tmp_path, CAMERAS["sentinel_a"])
    assert not any(tmp_path.iterdir()), "flash machines must never mint camera secrets"
    assert os.listdir(tmp_path) == []
