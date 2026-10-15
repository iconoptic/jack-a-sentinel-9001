from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import httpx
import respx

from sentinel_controller.evidence import export_evidence, sha256_file
from sentinel_controller.frigate_client import FrigateClient


@respx.mock
def test_evidence_export_against_fake_frigate(tmp_path: Path):
    base = "http://frigate.test"
    start = datetime(2026, 10, 14, 12, 0, 0, tzinfo=timezone.utc)
    end = datetime(2026, 10, 14, 12, 5, 0, tzinfo=timezone.utc)

    respx.post(f"{base}/api/exports/batch").respond(
        200,
        json={
            "export_ids": ["exp-1", "exp-2"],
            "results": [],
        },
    )

    def export_handler(request: httpx.Request):
        eid = request.url.path.split("/")[-1]
        return httpx.Response(
            200,
            json={
                "id": eid,
                "camera": "sentinel_a" if eid == "exp-1" else "sentinel_b",
                "name": eid,
                "date": start.timestamp(),
                "video_path": f"/media/frigate/exports/{eid}.mp4",
                "thumb_path": f"/media/frigate/exports/{eid}.webp",
                "in_progress": False,
            },
        )

    respx.get(url__regex=r".*/api/exports/exp-.*").mock(side_effect=export_handler)
    respx.get(url__regex=r".*/api/media/frigate/exports/.*").respond(200, content=b"VIDEO")
    respx.get(f"{base}/api/media/frigate/clips/review/thumb.webp").respond(
        200, content=b"THUMB"
    )

    client = httpx.Client(base_url=base)
    frigate = FrigateClient(base, client=client)

    out = export_evidence(
        evidence_root=tmp_path,
        session_start=start,
        session_end=end,
        camera_names=["sentinel_a", "sentinel_b"],
        review_ids=["review-1"],
        clock_source="pytest UTC",
        frigate=frigate,
        export_items=[
            {
                "camera": "sentinel_a",
                "start_time": start.timestamp(),
                "end_time": end.timestamp(),
            },
            {
                "camera": "sentinel_b",
                "start_time": start.timestamp(),
                "end_time": end.timestamp(),
            },
        ],
        review_thumb_paths=["/media/frigate/clips/review/thumb.webp"],
    )

    manifest = (out / "manifest.json").read_text(encoding="utf-8")
    assert "review-1" in manifest
    assert "sha256" in manifest
    clip = out / "clips" / "sentinel_a_exp-1.mp4"
    assert clip.is_file()
    assert sha256_file(clip) in manifest
    frigate.close()
