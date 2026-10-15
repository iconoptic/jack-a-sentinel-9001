from __future__ import annotations

import json

import pytest

from sentinel_controller.config import Config
from sentinel_controller.state_machine import SessionController, State


@pytest.fixture
def ctrl(config: Config, fake_frigate):
    published: list[tuple[str, str]] = []

    def pub(topic: str, payload: str) -> None:
        published.append((topic, payload))

    c = SessionController(
        config=config,
        frigate=fake_frigate,
        publish_mqtt=pub,
        now_fn=lambda: 1_000_000.0,
    )
    c._published = published  # type: ignore[attr-defined]
    return c


def _all_motion_off(ctrl: SessionController) -> None:
    for name in ctrl.config.frigate_names():
        ctrl.handle_mqtt(f"frigate/{name}/motion", b"OFF")


def test_person_alert_arms_all_cameras(ctrl: SessionController, load_fixture, fake_frigate):
    payload = json.dumps(load_fixture("review_person_new_alert.json"))
    ctrl.handle_mqtt("frigate/reviews", payload)

    assert ctrl.state == State.ARMED
    assert set(fake_frigate.created) == {"sentinel_b", "sentinel_c"}

    cmds = {t: json.loads(p) for t, p in ctrl._published}  # type: ignore[attr-defined]
    for cam_id in ("a", "b", "c"):
        topic = f"sentinel/{cam_id}/cmd"
        assert topic in cmds
        assert cmds[topic]["mode"] == "armed"
        assert cmds[topic]["ttl"] == 60


def test_ignore_sub_labels_skips_arm(config: Config, fake_frigate, load_fixture):
    config.controller.ignore_sub_labels = ["me"]
    published: list[tuple[str, str]] = []
    ctrl = SessionController(
        config=config,
        frigate=fake_frigate,
        publish_mqtt=lambda t, p: published.append((t, p)),
    )
    ctrl.handle_mqtt(
        "frigate/reviews",
        json.dumps(load_fixture("review_person_sub_label_me.json")),
    )
    assert ctrl.state == State.IDLE
    assert not fake_frigate.created
    assert not published


def test_motion_off_and_hold_enters_cooldown(ctrl: SessionController, load_fixture, fake_frigate):
    ctrl.handle_mqtt("frigate/reviews", json.dumps(load_fixture("review_person_new_alert.json")))
    _all_motion_off(ctrl)
    assert ctrl.hold_deadline == 1_000_000.0 + 60

    ctrl.tick(1_000_000.0 + 60)
    assert ctrl.state == State.IDLE
    assert len(fake_frigate.ended) == 2
    idle_cmds = [p for t, p in ctrl._published if t.endswith("/cmd") and "idle" in p]  # type: ignore[attr-defined]
    assert len(idle_cmds) == 3


def test_max_session_seconds_cap(ctrl: SessionController, load_fixture):
    ctrl.handle_mqtt("frigate/reviews", json.dumps(load_fixture("review_person_new_alert.json")))
    ctrl.handle_mqtt("frigate/sentinel_a/motion", b"ON")
    ctrl.tick(1_000_000.0 + 900)
    assert ctrl.state == State.IDLE


def test_alert_during_cooldown_rearms(ctrl: SessionController, load_fixture, fake_frigate):
    ctrl.handle_mqtt("frigate/reviews", json.dumps(load_fixture("review_person_new_alert.json")))
    ctrl.state = State.COOLDOWN
    ctrl.sync_events.clear()
    fake_frigate.created.clear()

    ctrl.handle_mqtt("frigate/reviews", json.dumps(load_fixture("review_person_new_alert.json")))
    assert ctrl.state == State.ARMED
    assert set(fake_frigate.created) == {"sentinel_b", "sentinel_c"}


def test_offline_from_idle_triggers_save_on_remaining(
    ctrl: SessionController, fake_frigate
):
    ctrl.handle_mqtt("sentinel/b/state", b"offline")
    assert ctrl.state == State.ARMED
    assert set(fake_frigate.created) == {"sentinel_a", "sentinel_c"}


def test_review_end_does_not_arm(ctrl: SessionController, load_fixture, fake_frigate):
    ctrl.handle_mqtt("frigate/reviews", json.dumps(load_fixture("review_end.json")))
    assert ctrl.state == State.IDLE
    assert not fake_frigate.created
