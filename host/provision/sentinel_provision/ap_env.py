from __future__ import annotations

import os
import re
import secrets
import shlex
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ApSettings:
    ssid: str
    psk: str
    channel: int
    bssid: str | None


_BSSID_RE = re.compile(r"^([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})$")

AP_ENV_HEADER = (
    "# Private camera AP. Bash-sourced by host/network/setup-ap.sh; read by sentinel-provision.\n"
    "# SSID and PSK are generated once by `sentinel-provision init`. The installer fills\n"
    "# WIFI_IFACE, CHANNEL and WIFI_BSSID. SSID must not contain SENTINEL.\n"
)
AP_KEYS = ("WIFI_IFACE", "SSID", "PSK", "CHANNEL", "WIFI_BSSID")


def generate_ssid() -> str:
    """Boring, random, hidden: `ap` + 6 hex. Never contains the project name."""
    return "ap" + secrets.token_hex(3)


def generate_psk() -> str:
    """128 bits as 32 hex chars (WPA2 passphrase is 8-63 characters)."""
    return secrets.token_hex(16)


def read_ap_env_raw(path: Path) -> dict[str, str]:
    """Parse KEY=VALUE lines (bash-ish quoting) without validating anything."""
    values: dict[str, str] = {}
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "'\"":
            val = val[1:-1]
        values[key] = val
    return values


def update_ap_env(path: Path, updates: dict[str, str]) -> bool:
    """Set keys in ap.env in place (created with the standard header when missing).

    Keeps unknown lines and comments. Returns True if the file changed.
    """
    for key in updates:
        if key not in AP_KEYS:
            raise ValueError(f"unknown ap.env key {key!r}")
    old = path.read_text() if path.is_file() else None
    lines = old.splitlines() if old is not None else AP_ENV_HEADER.splitlines()
    done: set[str] = set()
    out: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0].strip().removeprefix("export ").strip()
        if "=" in line and not line.lstrip().startswith("#") and key in updates:
            out.append(f"{key}={shlex.quote(updates[key])}")
            done.add(key)
        else:
            out.append(line)
    for key, value in updates.items():
        if key not in done:
            out.append(f"{key}={shlex.quote(value)}")
    new = "\n".join(out) + "\n"
    if new == old:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(new)
    os.chmod(path, 0o600)
    return True


def ensure_ap_env(path: Path) -> bool:
    """Create ap.env with a fresh SSID/PSK, or fill in an empty SSID/PSK. Never rotates."""
    current = read_ap_env_raw(path) if path.is_file() else {}
    updates: dict[str, str] = {}
    for key in AP_KEYS:
        if key not in current:
            updates[key] = ""
    if not current.get("SSID"):
        updates["SSID"] = generate_ssid()
    if not current.get("PSK"):
        updates["PSK"] = generate_psk()
    return update_ap_env(path, updates) if updates else False


def normalize_bssid(value: str) -> str:
    if not _BSSID_RE.match(value):
        raise ValueError(f"{value!r} is not a MAC address")
    return value.lower()


def load_ap_env(path: Path, *, require_bssid: bool = False) -> ApSettings:
    values = read_ap_env_raw(path)

    ssid = values.get("SSID", "")
    psk = values.get("PSK", "")
    channel_raw = values.get("CHANNEL", "")
    bssid = values.get("WIFI_BSSID") or values.get("BSSID") or None

    if not ssid or not psk:
        raise SystemExit(f"{path}: SSID and PSK must be set")
    if not channel_raw:
        raise SystemExit(f"{path}: CHANNEL must be set (1, 6, or 11)")
    channel = int(channel_raw)
    if channel not in (1, 6, 11):
        raise SystemExit(f"{path}: CHANNEL must be 1, 6, or 11 (got {channel})")
    if bssid and not _BSSID_RE.match(bssid):
        raise SystemExit(f"{path}: WIFI_BSSID is not a valid MAC")
    if require_bssid and not bssid:
        raise SystemExit(
            f"{path}: WIFI_BSSID is empty. Run scripts/install-fedora.sh on the host first "
            "(it records the AP's BSSID), then copy secrets with scripts/secrets-sync.sh."
        )

    return ApSettings(ssid=ssid, psk=psk, channel=channel, bssid=bssid.lower() if bssid else None)
