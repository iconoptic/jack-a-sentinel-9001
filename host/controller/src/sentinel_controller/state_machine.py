from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

from sentinel_controller.config import Config
from sentinel_controller.evidence import export_evidence
from sentinel_controller.frigate_client import FrigateClientProtocol
from sentinel_controller.triggers import parse_review_payload, review_id, review_qualifies

logger = logging.getLogger(__name__)


class State(str, Enum):
    IDLE = "idle"
    ARMED = "armed"
    COOLDOWN = "cooldown"


PublishFn = Callable[[str, str], None]


@dataclass
class SessionController:
    config: Config
    frigate: FrigateClientProtocol
    publish_mqtt: PublishFn
    now_fn: Callable[[], float] = field(default=lambda: datetime.now(timezone.utc).timestamp())

    state: State = State.IDLE
    session_start: datetime | None = None
    session_end: datetime | None = None
    trigger_camera: str | None = None
    review_ids: set[str] = field(default_factory=set)
    review_thumbs: list[str] = field(default_factory=list)
    sync_events: dict[str, str] = field(default_factory=dict)
    motion_on: dict[str, bool] = field(default_factory=dict)
    offline: set[str] = field(default_factory=set)
    armed_at: float | None = None
    last_arm_publish: float | None = None
    hold_deadline: float | None = None
    last_evidence_dir: str | None = None

    def handle_mqtt(self, topic: str, payload: str | bytes) -> None:
        if topic == "frigate/reviews":
            self._on_review(payload)
            return
        if topic.startswith("frigate/") and topic.endswith("/motion"):
            camera = topic.split("/")[1]
            self._on_motion(camera, payload)
            return
        if topic.startswith("sentinel/") and topic.endswith("/state"):
            parts = topic.split("/")
            if len(parts) >= 3:
                cam_id = parts[1]
                self._on_camera_state(cam_id, payload)
            return

    def tick(self, now: float | None = None) -> None:
        ts = self.now_fn() if now is None else now
        if self.state == State.ARMED:
            self._maybe_refresh_armed(ts)
            if self.armed_at is not None:
                if ts - self.armed_at >= self.config.controller.max_session_seconds:
                    logger.info("max_session_seconds reached")
                    self._begin_cooldown(ts)
                    return
            if self.hold_deadline is not None and ts >= self.hold_deadline:
                logger.info("hold_seconds satisfied after all motion OFF")
                self._begin_cooldown(ts)

    def _on_review(self, payload: str | bytes) -> None:
        msg = parse_review_payload(payload)
        qualifies, camera = review_qualifies(
            msg,
            trigger_labels=self.config.controller.trigger_labels,
            ignore_sub_labels=self.config.controller.ignore_sub_labels,
        )
        if not qualifies or not camera:
            return
        rid = review_id(msg)
        if rid:
            self.review_ids.add(rid)
        thumb = (msg.get("after") or {}).get("thumb_path")
        if thumb:
            self.review_thumbs.append(str(thumb))

        if self.state == State.COOLDOWN:
            logger.info("qualifying alert during COOLDOWN — re-arming")
            self._abort_cooldown_cleanup()
            self._enter_armed(camera, ts=self.now_fn())
            return
        if self.state == State.ARMED:
            self.trigger_camera = camera
            return
        self._enter_armed(camera, ts=self.now_fn())

    def _on_motion(self, camera_name: str, payload: str | bytes) -> None:
        if self.state != State.ARMED:
            return
        if camera_name not in self.config.frigate_names():
            return
        text = payload.decode("utf-8") if isinstance(payload, bytes) else str(payload)
        text = text.strip().upper()
        is_on = text == "ON"
        self.motion_on[camera_name] = is_on
        if is_on:
            self.hold_deadline = None
        else:
            self._recompute_hold(self.now_fn())

    def _on_camera_state(self, camera_id: str, payload: str | bytes) -> None:
        text = payload.decode("utf-8") if isinstance(payload, bytes) else str(payload)
        text = text.strip().lower()
        camera_name = None
        for cam in self.config.cameras:
            if cam.id == camera_id:
                camera_name = cam.frigate_name
                break
        if not camera_name:
            return
        if text == "offline":
            logger.warning("camera_offline %s", camera_name)
            self.offline.add(camera_name)
            self.motion_on[camera_name] = False
            if self.state == State.IDLE:
                self._enter_armed(camera_name, ts=self.now_fn(), reason="camera_offline")
            elif self.state == State.ARMED:
                self._recompute_hold(self.now_fn())
            elif self.state == State.COOLDOWN:
                self._abort_cooldown_cleanup()
                self._enter_armed(camera_name, ts=self.now_fn(), reason="camera_offline")

    def _enter_armed(self, trigger_camera: str, *, ts: float, reason: str = "review") -> None:
        logger.info("ARMED (trigger=%s reason=%s)", trigger_camera, reason)
        self.state = State.ARMED
        if self.session_start is None:
            self.session_start = datetime.fromtimestamp(ts, tz=timezone.utc)
        self.trigger_camera = trigger_camera
        self.armed_at = ts
        self.last_arm_publish = None
        self.hold_deadline = None
        for name in self.config.frigate_names():
            self.motion_on.setdefault(name, False)
        self._publish_armed_all(ts)
        self._ensure_sync_events(trigger_camera)

    def _ensure_sync_events(self, trigger_camera: str) -> None:
        for name in self.config.frigate_names():
            if name == trigger_camera:
                continue
            if name in self.offline:
                continue
            if name in self.sync_events:
                continue
            event_id = self.frigate.create_sentinel_sync(name)
            self.sync_events[name] = event_id
            logger.info("sentinel_sync create %s -> %s", name, event_id)

    def _publish_armed_all(self, ts: float) -> None:
        ttl = self.config.controller.armed_ttl_seconds
        body = json.dumps({"mode": "armed", "ttl": ttl})
        for cam in self.config.cameras:
            self.publish_mqtt(f"sentinel/{cam.id}/cmd", body)
        self.last_arm_publish = ts

    def _publish_idle_all(self) -> None:
        body = json.dumps({"mode": "idle"})
        for cam in self.config.cameras:
            self.publish_mqtt(f"sentinel/{cam.id}/cmd", body)

    def _maybe_refresh_armed(self, ts: float) -> None:
        refresh = self.config.controller.arm_refresh_seconds
        if self.last_arm_publish is None or ts - self.last_arm_publish >= refresh:
            self._publish_armed_all(ts)

    def _active_for_hold(self) -> list[str]:
        return [n for n in self.config.frigate_names() if n not in self.offline]

    def _recompute_hold(self, ts: float) -> None:
        if self.state != State.ARMED:
            return
        active = self._active_for_hold()
        if not active:
            self.hold_deadline = ts + self.config.controller.hold_seconds
            return
        if all(not self.motion_on.get(n, False) for n in active):
            self.hold_deadline = ts + self.config.controller.hold_seconds
        else:
            self.hold_deadline = None

    def _begin_cooldown(self, ts: float) -> None:
        if self.state != State.ARMED:
            return
        logger.info("COOLDOWN")
        self.state = State.COOLDOWN
        self.session_end = datetime.fromtimestamp(ts, tz=timezone.utc)
        for _cam, eid in list(self.sync_events.items()):
            try:
                self.frigate.end_event(eid)
            except Exception:
                logger.exception("end_event %s", eid)
        self.sync_events.clear()
        self._publish_idle_all()
        self._finalize_cooldown()

    def _finalize_cooldown(self) -> None:
        if self.state != State.COOLDOWN:
            return
        self._run_evidence_export()
        self._reset_session_fields()
        self.state = State.IDLE

    def _run_evidence_export(self) -> None:
        if self.session_start is None or self.session_end is None:
            return
        start_ts = self.session_start.timestamp()
        end_ts = self.session_end.timestamp()
        items = [
            {
                "camera": name,
                "start_time": start_ts,
                "end_time": end_ts,
                "friendly_name": f"sentinel_{name}",
            }
            for name in self.config.frigate_names()
            if name not in self.offline
        ]
        try:
            out = export_evidence(
                evidence_root=self.config.paths.evidence_dir,
                session_start=self.session_start,
                session_end=self.session_end,
                camera_names=self.config.frigate_names(),
                review_ids=sorted(self.review_ids),
                clock_source=self.config.paths.clock_source,
                frigate=self.frigate,
                export_items=items,
                review_thumb_paths=self.review_thumbs,
            )
            self.last_evidence_dir = str(out)
            logger.info("evidence exported to %s", out)
        except Exception:
            logger.exception("evidence export failed")

    def _abort_cooldown_cleanup(self) -> None:
        """Re-arm during COOLDOWN: sync events may already be ended; start fresh."""
        self.sync_events.clear()
        self.session_start = None
        self.session_end = None
        self.review_ids.clear()
        self.review_thumbs.clear()

    def _reset_session_fields(self) -> None:
        self.session_start = None
        self.session_end = None
        self.trigger_camera = None
        self.review_ids.clear()
        self.review_thumbs.clear()
        self.armed_at = None
        self.last_arm_publish = None
        self.hold_deadline = None
        self.motion_on.clear()
