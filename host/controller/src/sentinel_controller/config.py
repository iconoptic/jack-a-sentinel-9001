from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Camera:
    frigate_name: str
    id: str
    static_ip: str


@dataclass
class ControllerSettings:
    trigger_labels: list[str] = field(default_factory=lambda: ["person"])
    hold_seconds: int = 60
    max_session_seconds: int = 900
    ignore_sub_labels: list[str] = field(default_factory=list)
    notify: bool = False
    arm_refresh_seconds: int = 20
    armed_ttl_seconds: int = 60


@dataclass
class MqttSettings:
    host: str = "10.77.0.1"
    port: int = 1883
    username: str = "controller"
    password: str = ""


@dataclass
class FrigateSettings:
    url: str = "http://127.0.0.1:5000"
    api_key: str = ""


@dataclass
class PathSettings:
    evidence_dir: Path = Path("/var/lib/sentinel/evidence")
    clock_source: str = "system UTC (chrony on Fedora host)"


@dataclass
class Config:
    controller: ControllerSettings = field(default_factory=ControllerSettings)
    mqtt: MqttSettings = field(default_factory=MqttSettings)
    frigate: FrigateSettings = field(default_factory=FrigateSettings)
    paths: PathSettings = field(default_factory=PathSettings)
    cameras: list[Camera] = field(default_factory=list)

    def camera_by_frigate(self, name: str) -> Camera | None:
        for cam in self.cameras:
            if cam.frigate_name == name:
                return cam
        return None

    def frigate_names(self) -> list[str]:
        return [c.frigate_name for c in self.cameras]


DEFAULT_CAMERAS = [
    Camera("sentinel_a", "a", "10.77.0.11"),
    Camera("sentinel_b", "b", "10.77.0.12"),
    Camera("sentinel_c", "c", "10.77.0.13"),
]


def load_config(path: Path | None = None) -> Config:
    cfg = Config(cameras=list(DEFAULT_CAMERAS))
    if path is None:
        path = Path(os.environ.get("SENTINEL_CONFIG", "config.toml"))
    if path.is_file():
        with path.open("rb") as f:
            raw = tomllib.load(f)
        _apply_toml(cfg, raw)

    if pw := os.environ.get("SENTINEL_MQTT_PASSWORD"):
        cfg.mqtt.password = pw
    if key := os.environ.get("SENTINEL_FRIGATE_API_KEY"):
        cfg.frigate.api_key = key
    if ev := os.environ.get("SENTINEL_EVIDENCE_DIR"):
        cfg.paths.evidence_dir = Path(ev)
    if url := os.environ.get("SENTINEL_FRIGATE_URL"):
        cfg.frigate.url = url.rstrip("/")
    return cfg


def _apply_toml(cfg: Config, raw: dict) -> None:
    if ctrl := raw.get("controller"):
        cfg.controller = ControllerSettings(
            trigger_labels=list(ctrl.get("trigger_labels", cfg.controller.trigger_labels)),
            hold_seconds=int(ctrl.get("hold_seconds", cfg.controller.hold_seconds)),
            max_session_seconds=int(
                ctrl.get("max_session_seconds", cfg.controller.max_session_seconds)
            ),
            ignore_sub_labels=list(
                ctrl.get("ignore_sub_labels", cfg.controller.ignore_sub_labels)
            ),
            notify=bool(ctrl.get("notify", cfg.controller.notify)),
            arm_refresh_seconds=int(
                ctrl.get("arm_refresh_seconds", cfg.controller.arm_refresh_seconds)
            ),
            armed_ttl_seconds=int(
                ctrl.get("armed_ttl_seconds", cfg.controller.armed_ttl_seconds)
            ),
        )
    if mqtt := raw.get("mqtt"):
        cfg.mqtt = MqttSettings(
            host=str(mqtt.get("host", cfg.mqtt.host)),
            port=int(mqtt.get("port", cfg.mqtt.port)),
            username=str(mqtt.get("username", cfg.mqtt.username)),
            password=str(mqtt.get("password", cfg.mqtt.password)),
        )
    if frigate := raw.get("frigate"):
        cfg.frigate = FrigateSettings(
            url=str(frigate.get("url", cfg.frigate.url)).rstrip("/"),
            api_key=str(frigate.get("api_key", cfg.frigate.api_key)),
        )
    if paths := raw.get("paths"):
        cfg.paths = PathSettings(
            evidence_dir=Path(paths.get("evidence_dir", cfg.paths.evidence_dir)),
            clock_source=str(paths.get("clock_source", cfg.paths.clock_source)),
        )
    if cameras := raw.get("cameras"):
        cfg.cameras = [
            Camera(
                frigate_name=str(c["frigate_name"]),
                id=str(c["id"]),
                static_ip=str(c.get("static_ip", "")),
            )
            for c in cameras
        ]
