from __future__ import annotations

import logging
import time
from typing import Any, Protocol

import httpx

logger = logging.getLogger(__name__)

SYNC_LABEL = "sentinel_sync"


class FrigateClientProtocol(Protocol):
    def create_sentinel_sync(self, camera_name: str) -> str: ...

    def end_event(self, event_id: str) -> None: ...

    def export_session_recordings(
        self,
        items: list[dict[str, Any]],
        *,
        poll_timeout_s: float = 120.0,
    ) -> list[dict[str, Any]]: ...

    def download_media_path(self, media_path: str) -> bytes: ...


class FrigateClient:
    def __init__(self, base_url: str, api_key: str = "", *, client: httpx.Client | None = None):
        self.base_url = base_url.rstrip("/")
        headers: dict[str, str] = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self._client = client or httpx.Client(base_url=self.base_url, headers=headers, timeout=60.0)
        self._owns_client = client is None

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def create_sentinel_sync(self, camera_name: str) -> str:
        r = self._client.post(
            f"/api/events/{camera_name}/{SYNC_LABEL}/create",
            json={"duration": None, "include_recording": True},
        )
        r.raise_for_status()
        body = r.json()
        event_id = body.get("event_id")
        if not event_id:
            raise RuntimeError(f"Frigate create event missing event_id: {body}")
        return str(event_id)

    def end_event(self, event_id: str) -> None:
        r = self._client.put(f"/api/events/{event_id}/end", json={})
        r.raise_for_status()

    def get_export(self, export_id: str) -> dict[str, Any]:
        r = self._client.get(f"/api/exports/{export_id}")
        r.raise_for_status()
        return r.json()

    def export_session_recordings(
        self,
        items: list[dict[str, Any]],
        *,
        poll_timeout_s: float = 120.0,
    ) -> list[dict[str, Any]]:
        if not items:
            return []
        r = self._client.post(
            "/api/exports/batch",
            json={
                "items": items,
                "new_case_name": "sentinel_session",
            },
        )
        r.raise_for_status()
        batch = r.json()
        export_ids = batch.get("export_ids") or []
        deadline = time.monotonic() + poll_timeout_s
        exports: list[dict[str, Any]] = []
        for export_id in export_ids:
            while time.monotonic() < deadline:
                meta = self.get_export(export_id)
                if not meta.get("in_progress"):
                    exports.append(meta)
                    break
                time.sleep(0.05)
            else:
                raise TimeoutError(f"export {export_id} did not complete")
        return exports

    def download_media_path(self, media_path: str) -> bytes:
        path = media_path if media_path.startswith("/") else f"/{media_path}"
        r = self._client.get(f"/api{path}")
        r.raise_for_status()
        return r.content
