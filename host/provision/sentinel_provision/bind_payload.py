from __future__ import annotations

import json
from typing import Any

from sentinel_provision.cameras import (
    DEFAULT_GATEWAY,
    DEFAULT_HOST_ID,
    DEFAULT_MQTT_BROKER,
    DEFAULT_MQTT_PORT,
    DEFAULT_NETMASK,
    CameraSpec,
)

# Exact key set for Phase 3–5 (no mqtt_ca_pem).
BIND_JSON_KEYS = (
    "host_id",
    "camera_id",
    "static_ip",
    "gateway",
    "netmask",
    "wifi_bssid",
    "wifi_channel",
    "mqtt_broker",
    "mqtt_port",
    "mqtt_username",
    "mqtt_password",
    "stream_token",
)


def build_bind_payload(
    cam: CameraSpec,
    *,
    host_id: str = DEFAULT_HOST_ID,
    mqtt_password: str,
    stream_token: str,
    wifi_bssid: str,
    wifi_channel: int,
    gateway: str = DEFAULT_GATEWAY,
    netmask: str = DEFAULT_NETMASK,
    mqtt_broker: str = DEFAULT_MQTT_BROKER,
    mqtt_port: int = DEFAULT_MQTT_PORT,
) -> dict[str, Any]:
    return {
        "host_id": host_id,
        "camera_id": cam.camera_id,
        "static_ip": cam.static_ip,
        "gateway": gateway,
        "netmask": netmask,
        "wifi_bssid": wifi_bssid.lower(),
        "wifi_channel": int(wifi_channel),
        "mqtt_broker": mqtt_broker,
        "mqtt_port": int(mqtt_port),
        "mqtt_username": cam.mqtt_username,
        "mqtt_password": mqtt_password,
        "stream_token": stream_token,
    }


def bind_payload_json(payload: dict[str, Any]) -> str:
    """Compact JSON for the sentinel-bind endpoint (UTF-8)."""
    missing = [k for k in BIND_JSON_KEYS if k not in payload]
    if missing:
        raise ValueError(f"bind payload missing keys: {missing}")
    extra = set(payload) - set(BIND_JSON_KEYS)
    if extra:
        raise ValueError(f"unexpected bind keys (Phase 6+ fields go in later phases): {sorted(extra)}")
    ordered = {k: payload[k] for k in BIND_JSON_KEYS}
    return json.dumps(ordered, separators=(",", ":"))
