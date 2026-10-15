from __future__ import annotations

import json
from pathlib import Path

import pytest

from sentinel_controller.config import Config, load_config


FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def config(tmp_path: Path) -> Config:
    cfg = load_config(Path(__file__).resolve().parents[1] / "config.toml")
    cfg.paths.evidence_dir = tmp_path / "evidence"
    return cfg


@pytest.fixture
def load_fixture():
    def _load(name: str) -> dict:
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    return _load


class FakeFrigate:
    def __init__(self) -> None:
        self.created: list[str] = []
        self.ended: list[str] = []
        self._next_id = 1
        self.export_calls: list[list] = []

    def create_sentinel_sync(self, camera_name: str) -> str:
        self.created.append(camera_name)
        eid = f"sync-{camera_name}-{self._next_id}"
        self._next_id += 1
        return eid

    def end_event(self, event_id: str) -> None:
        self.ended.append(event_id)

    def export_session_recordings(self, items, *, poll_timeout_s: float = 120.0):
        self.export_calls.append(items)
        out = []
        for item in items:
            cam = item["camera"]
            out.append(
                {
                    "id": f"exp-{cam}",
                    "camera": cam,
                    "video_path": f"/media/frigate/exports/{cam}.mp4",
                    "thumb_path": f"/media/frigate/exports/{cam}.webp",
                    "in_progress": False,
                }
            )
        return out

    def download_media_path(self, media_path: str) -> bytes:
        return f"bytes-for-{media_path}".encode()


@pytest.fixture
def fake_frigate() -> FakeFrigate:
    return FakeFrigate()
