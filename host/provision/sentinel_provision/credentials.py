from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path

from sentinel_provision.cameras import CameraSpec


def generate_secret_hex(nbytes: int = 24) -> str:
    return secrets.token_hex(nbytes)


@dataclass
class CameraSecrets:
    mqtt_password: str
    stream_token: str


def write_private(path: Path, text: str) -> None:
    """Write a secret file that is never group/world readable, even for an instant."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    os.chmod(path, 0o600)


def load_camera_secrets(secrets_dir: Path, cam: CameraSpec) -> CameraSecrets:
    """Read-only: secrets/cameras/<id>.env must already exist (flash machines never mint them)."""
    env_path = secrets_dir / "cameras" / f"{cam.camera_id}.env"
    if not env_path.is_file():
        raise SystemExit(
            f"Missing {env_path}. Secrets are generated on the Fedora host "
            "(scripts/install-fedora.sh); copy them here with scripts/secrets-sync.sh pull."
        )
    values = _parse_env_file(env_path)
    if not values.get("MQTT_PASSWORD") or not values.get("STREAM_TOKEN"):
        raise SystemExit(f"{env_path}: MQTT_PASSWORD and STREAM_TOKEN must both be set")
    return CameraSecrets(values["MQTT_PASSWORD"], values["STREAM_TOKEN"])


def load_or_create_camera_secrets(
    secrets_dir: Path,
    cam: CameraSpec,
    *,
    adopt_mqtt_password: str | None = None,
    adopt_stream_token: str | None = None,
) -> CameraSecrets:
    """
    Return existing MQTT password and stream token for this camera, or create new ones.
    Writes `secrets/cameras/<id>.env` (gitignored layout from CONTRACTS.md).

    `adopt_*` carry over values an older generate-secrets.sh already put in
    mosquitto/users and frigate.env, so upgrading never desynchronises them.
    """
    cam_dir = secrets_dir / "cameras"
    cam_dir.mkdir(parents=True, exist_ok=True)
    env_path = cam_dir / f"{cam.camera_id}.env"

    if env_path.is_file():
        values = _parse_env_file(env_path)
        mqtt_password = values.get("MQTT_PASSWORD", "")
        stream_token = values.get("STREAM_TOKEN", "")
        if mqtt_password and stream_token:
            return CameraSecrets(mqtt_password=mqtt_password, stream_token=stream_token)

    mqtt_password = adopt_mqtt_password or generate_secret_hex(24)
    stream_token = adopt_stream_token or generate_secret_hex(24)
    _write_env_file(
        env_path,
        {
            "MQTT_USERNAME": cam.mqtt_username,
            "MQTT_PASSWORD": mqtt_password,
            "STREAM_TOKEN": stream_token,
        },
    )
    return CameraSecrets(mqtt_password=mqtt_password, stream_token=stream_token)


def ensure_mqtt_user_line(users_path: Path, username: str, password: str) -> bool:
    """
    Append `username:password` to secrets/mosquitto/users if missing.
    Returns True if the file was modified.
    """
    users_path.parent.mkdir(parents=True, exist_ok=True)
    existing = ""
    if users_path.is_file():
        existing = users_path.read_text()
    for line in existing.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.split(":", 1)[0] == username:
            return False
    prefix = "\n" if existing and not existing.endswith("\n") else ""
    write_private(users_path, f"{existing}{prefix}{username}:{password}\n")
    return True


def upsert_frigate_stream_token(frigate_env: Path, env_key: str, token: str) -> bool:
    """Set FRIGATE_STREAM_TOKEN_* in secrets/frigate.env. Returns True if modified."""
    frigate_env.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if frigate_env.is_file():
        lines = frigate_env.read_text().splitlines()
    key_prefix = f"{env_key}="
    replaced = False
    out: list[str] = []
    for line in lines:
        if line.startswith(key_prefix):
            out.append(f"{env_key}={token}")
            replaced = True
        else:
            out.append(line)
    if not replaced:
        if out and out[-1].strip():
            out.append("")
        out.append(f"{env_key}={token}")
    new_text = "\n".join(out) + "\n"
    old_text = frigate_env.read_text() if frigate_env.is_file() else ""
    if new_text == old_text:
        return False
    write_private(frigate_env, new_text)
    return True


def read_users(users_path: Path) -> dict[str, str]:
    """`username:password` lines of secrets/mosquitto/users."""
    out: dict[str, str] = {}
    if users_path.is_file():
        for raw in users_path.read_text().splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and ":" in line:
                user, _, password = line.partition(":")
                out[user] = password
    return out


def parse_env_file(path: Path) -> dict[str, str]:
    return _parse_env_file(path) if path.is_file() else {}


def _parse_env_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def _write_env_file(path: Path, values: dict[str, str]) -> None:
    lines = ["# Written by sentinel-provision; do not commit."]
    for key in sorted(values):
        lines.append(f"{key}={values[key]}")
    write_private(path, "\n".join(lines) + "\n")
