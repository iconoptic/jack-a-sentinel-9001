"""CSV input for ESP-IDF's nvs_partition_gen: a board that boots already BOUND.

Key names are the ones firmware/sentinel/components/sentinel_bind/bind_nvs.c reads from
NVS namespace "bind". Wi-Fi credentials ride along (wifi_ssid / wifi_psk) because nothing
ran network_provisioning to put them in the esp_wifi namespace.
"""

from __future__ import annotations

import csv
import io
from typing import Any

NAMESPACE = "bind"

# payload key (CONTRACTS.md bind JSON) -> NVS key, all strings
_STRING_KEYS = (
    ("host_id", "host_id"),
    ("camera_id", "camera_id"),
    ("static_ip", "static_ip"),
    ("gateway", "gateway"),
    ("netmask", "netmask"),
    ("wifi_bssid", "wifi_bssid"),
    ("mqtt_broker", "mqtt_broker"),
    ("mqtt_username", "mqtt_user"),
    ("mqtt_password", "mqtt_pass"),
    ("stream_token", "stream_tok"),
)

# NVS key names are limited to 15 characters.
_MAX_NVS_KEY = 15
_MAX_LEN = {"wifi_ssid": 32, "wifi_psk": 63}


def bind_nvs_csv(payload: dict[str, Any], *, wifi_ssid: str, wifi_psk: str) -> str:
    if not 1 <= len(wifi_ssid.encode()) <= _MAX_LEN["wifi_ssid"]:
        raise ValueError("SSID must be 1-32 bytes")
    if not 8 <= len(wifi_psk) <= _MAX_LEN["wifi_psk"]:
        raise ValueError("PSK must be 8-63 characters")

    rows: list[list[str]] = [["key", "type", "encoding", "value"], [NAMESPACE, "namespace", "", ""]]
    rows.append(["bound", "data", "u8", "1"])
    for src, key in _STRING_KEYS:
        value = str(payload[src])
        if not value:
            raise ValueError(f"bind payload field {src} is empty")
        rows.append([key, "data", "string", value])
    rows.append(["wifi_ssid", "data", "string", wifi_ssid])
    rows.append(["wifi_psk", "data", "string", wifi_psk])
    rows.append(["wifi_ch", "data", "u8", str(int(payload["wifi_channel"]))])
    rows.append(["mqtt_port", "data", "u16", str(int(payload["mqtt_port"]))])

    for row in rows[1:]:
        if len(row[0]) > _MAX_NVS_KEY:
            raise ValueError(f"NVS key {row[0]!r} is longer than {_MAX_NVS_KEY} characters")

    buf = io.StringIO()
    csv.writer(buf, lineterminator="\n").writerows(rows)
    return buf.getvalue()
