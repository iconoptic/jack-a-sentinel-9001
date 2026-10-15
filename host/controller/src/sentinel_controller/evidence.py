from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sentinel_controller.frigate_client import FrigateClientProtocol


def utc_session_dir_name(start: datetime) -> str:
    return start.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def export_evidence(
    *,
    evidence_root: Path,
    session_start: datetime,
    session_end: datetime,
    camera_names: list[str],
    review_ids: list[str],
    clock_source: str,
    frigate: FrigateClientProtocol,
    export_items: list[dict[str, Any]],
    review_thumb_paths: list[str] | None = None,
) -> Path:
    """Pull Frigate exports and review thumbs into evidence/<UTC>/manifest.json."""
    out_dir = evidence_root / utc_session_dir_name(session_start)
    out_dir.mkdir(parents=True, exist_ok=True)

    exports_meta = frigate.export_session_recordings(export_items)
    files: list[dict[str, Any]] = []

    for meta in exports_meta:
        camera = meta["camera"]
        video_path = meta["video_path"]
        rel_name = f"clips/{camera}_{meta['id']}.mp4"
        dest = out_dir / rel_name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(frigate.download_media_path(video_path))
        files.append(
            {
                "kind": "clip",
                "camera": camera,
                "relative_path": rel_name,
                "sha256": sha256_file(dest),
                "frigate_export_id": meta["id"],
            }
        )
        thumb_path = meta.get("thumb_path")
        if thumb_path:
            rel_thumb = f"snapshots/{camera}_{meta['id']}_export.webp"
            tdest = out_dir / rel_thumb
            tdest.parent.mkdir(parents=True, exist_ok=True)
            tdest.write_bytes(frigate.download_media_path(thumb_path))
            files.append(
                {
                    "kind": "snapshot",
                    "camera": camera,
                    "relative_path": rel_thumb,
                    "sha256": sha256_file(tdest),
                    "source": "export_thumb",
                }
            )

    for idx, thumb in enumerate(review_thumb_paths or []):
        rel = f"snapshots/review_{idx}.webp"
        dest = out_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(frigate.download_media_path(thumb))
        files.append(
            {
                "kind": "snapshot",
                "relative_path": rel,
                "sha256": sha256_file(dest),
                "source": "review_thumb",
            }
        )

    manifest = {
        "session_start_utc": session_start.astimezone(timezone.utc).isoformat(),
        "session_end_utc": session_end.astimezone(timezone.utc).isoformat(),
        "cameras": camera_names,
        "review_ids": review_ids,
        "files": files,
        "clock_source": clock_source,
    }
    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return out_dir
