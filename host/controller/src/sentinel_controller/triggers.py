from __future__ import annotations

import json
from typing import Any


def parse_review_payload(payload: str | bytes | dict) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8")
    return json.loads(payload)


def review_qualifies(
    message: dict[str, Any],
    *,
    trigger_labels: list[str],
    ignore_sub_labels: list[str],
) -> tuple[bool, str | None]:
    """Return (qualifies, camera_name) for a frigate/reviews MQTT payload."""
    msg_type = message.get("type")
    if msg_type not in ("new", "update"):
        return False, None

    after = message.get("after") or {}
    if after.get("severity") != "alert":
        return False, None

    data = after.get("data") or {}
    objects = set(data.get("objects") or [])
    if not objects.intersection(trigger_labels):
        return False, None

    sub_labels = set(data.get("sub_labels") or [])
    if sub_labels.intersection(ignore_sub_labels):
        return False, None

    camera = after.get("camera")
    if not camera:
        return False, None
    return True, str(camera)


def review_id(message: dict[str, Any]) -> str | None:
    after = message.get("after") or {}
    rid = after.get("id")
    return str(rid) if rid else None
