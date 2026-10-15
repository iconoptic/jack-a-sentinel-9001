from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CameraSpec:
    """Frigate / go2rtc name and CONTRACTS.md network identity."""

    frigate_name: str
    camera_id: str
    static_ip: str
    mqtt_username: str
    stream_token_env: str


CAMERAS: dict[str, CameraSpec] = {
    "sentinel_a": CameraSpec(
        frigate_name="sentinel_a",
        camera_id="a",
        static_ip="10.77.0.11",
        mqtt_username="cam_a",
        stream_token_env="FRIGATE_STREAM_TOKEN_A",
    ),
    "sentinel_b": CameraSpec(
        frigate_name="sentinel_b",
        camera_id="b",
        static_ip="10.77.0.12",
        mqtt_username="cam_b",
        stream_token_env="FRIGATE_STREAM_TOKEN_B",
    ),
    "sentinel_c": CameraSpec(
        frigate_name="sentinel_c",
        camera_id="c",
        static_ip="10.77.0.13",
        mqtt_username="cam_c",
        stream_token_env="FRIGATE_STREAM_TOKEN_C",
    ),
}

DEFAULT_HOST_ID = "fedora-cubicle-1"
DEFAULT_GATEWAY = "10.77.0.1"
DEFAULT_NETMASK = "255.255.255.0"
DEFAULT_MQTT_BROKER = "10.77.0.1"
DEFAULT_MQTT_PORT = 1883
SEC2_USERNAME = "sentinel"


def get_camera(frigate_name: str) -> CameraSpec:
    try:
        return CAMERAS[frigate_name]
    except KeyError as exc:
        names = ", ".join(sorted(CAMERAS))
        raise SystemExit(f"Unknown camera {frigate_name!r}. Expected one of: {names}") from exc
