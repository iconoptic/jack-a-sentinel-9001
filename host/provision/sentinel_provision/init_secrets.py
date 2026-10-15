"""Generate every secret the deployment needs, once, into the gitignored secrets/ tree.

Layout (all files 0600, directories 0700):

    secrets/ap.env                  SSID, PSK, WIFI_IFACE, CHANNEL, WIFI_BSSID
    secrets/cameras/<id>.env        MQTT_USERNAME, MQTT_PASSWORD, STREAM_TOKEN   (a, b, c)
    secrets/frigate.env             podman EnvironmentFile: Frigate MQTT login + stream tokens
    secrets/mosquitto/users         username:password, input for hash-mqtt-passwords.sh
    secrets/mosquitto/acl           from host/mosquitto/acl.example + one block per camera
    secrets/mosquitto/controller.password

Safe to re-run: existing values are kept, only missing ones are generated.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from sentinel_provision.ap_env import ensure_ap_env
from sentinel_provision.cameras import CAMERAS, CameraSpec
from sentinel_provision.credentials import (
    ensure_mqtt_user_line,
    generate_secret_hex,
    load_or_create_camera_secrets,
    parse_env_file,
    read_users,
    upsert_frigate_stream_token,
    write_private,
)
from sentinel_provision.mosquitto_config import ensure_acl_block

SERVICE_USERS = ("frigate", "controller")


@dataclass
class InitResult:
    created: list[str] = field(default_factory=list)
    kept: list[str] = field(default_factory=list)

    def note(self, what: str, changed: bool) -> None:
        (self.created if changed else self.kept).append(what)


def _private_dirs(secrets_dir: Path) -> None:
    for d in (secrets_dir, secrets_dir / "cameras", secrets_dir / "mosquitto"):
        d.mkdir(parents=True, exist_ok=True)
        os.chmod(d, 0o700)


def init_secrets(
    secrets_dir: Path, repo_root: Path, cameras: list[CameraSpec] | None = None
) -> InitResult:
    cams = cameras if cameras is not None else list(CAMERAS.values())
    res = InitResult()
    _private_dirs(secrets_dir)

    res.note("ap.env (SSID, PSK)", ensure_ap_env(secrets_dir / "ap.env"))

    users_path = secrets_dir / "mosquitto" / "users"
    frigate_env = secrets_dir / "frigate.env"
    fenv = parse_env_file(frigate_env)

    # Service accounts. Older generate-secrets.sh wrote these into users + frigate.env.
    users = read_users(users_path)
    frigate_pw = users.get("frigate") or fenv.get("FRIGATE_MQTT_PASSWORD") or generate_secret_hex(24)
    controller_pw = users.get("controller") or generate_secret_hex(24)
    res.note("mqtt user frigate", ensure_mqtt_user_line(users_path, "frigate", frigate_pw))
    res.note("mqtt user controller", ensure_mqtt_user_line(users_path, "controller", controller_pw))

    changed = False
    for key, value in (
        ("FRIGATE_MQTT_HOST", "127.0.0.1"),
        ("FRIGATE_MQTT_USER", "frigate"),
        ("FRIGATE_MQTT_PASSWORD", frigate_pw),
    ):
        if fenv.get(key) != value:
            changed |= upsert_frigate_stream_token(frigate_env, key, value)
    res.note("frigate.env (MQTT login)", changed)
    write_private(secrets_dir / "mosquitto" / "controller.password", controller_pw)

    for cam in cams:
        users = read_users(users_path)
        fenv = parse_env_file(frigate_env)
        existed = (secrets_dir / "cameras" / f"{cam.camera_id}.env").is_file()
        creds = load_or_create_camera_secrets(
            secrets_dir,
            cam,
            adopt_mqtt_password=users.get(cam.mqtt_username),
            adopt_stream_token=fenv.get(cam.stream_token_env),
        )
        changed = ensure_mqtt_user_line(users_path, cam.mqtt_username, creds.mqtt_password)
        changed |= upsert_frigate_stream_token(frigate_env, cam.stream_token_env, creds.stream_token)
        changed |= ensure_acl_block(secrets_dir / "mosquitto" / "acl", cam, repo_root=repo_root)
        res.note(f"camera {cam.camera_id} (mqtt login, stream token, acl)", changed or not existed)

    return res
