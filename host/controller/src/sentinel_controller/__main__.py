from __future__ import annotations

import logging
import signal
import sys
import threading
import time
from pathlib import Path

import paho.mqtt.client as mqtt

from sentinel_controller.config import load_config
from sentinel_controller.frigate_client import FrigateClient
from sentinel_controller.state_machine import SessionController

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("sentinel_controller")


def main() -> None:
    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    cfg = load_config(config_path)
    frigate = FrigateClient(cfg.frigate.url, cfg.frigate.api_key)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="sentinel-controller")
    if cfg.mqtt.username:
        client.username_pw_set(cfg.mqtt.username, cfg.mqtt.password or None)

    controller = SessionController(
        config=cfg,
        frigate=frigate,
        publish_mqtt=lambda topic, payload: client.publish(topic, payload, qos=1),
    )

    def on_message(_client, _userdata, msg) -> None:
        try:
            controller.handle_mqtt(msg.topic, msg.payload)
        except Exception:
            logger.exception("handle_mqtt %s", msg.topic)

    client.on_message = on_message
    client.connect(cfg.mqtt.host, cfg.mqtt.port, keepalive=60)

    topics = ["frigate/reviews"]
    for name in cfg.frigate_names():
        topics.append(f"frigate/{name}/motion")
    for cam in cfg.cameras:
        topics.append(f"sentinel/{cam.id}/state")

    for topic in topics:
        client.subscribe(topic, qos=1)
        logger.info("subscribed %s", topic)

    stop = threading.Event()

    def _stop(*_args) -> None:
        stop.set()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    client.loop_start()
    try:
        while not stop.is_set():
            controller.tick()
            time.sleep(0.5)
    finally:
        client.loop_stop()
        client.disconnect()
        frigate.close()


if __name__ == "__main__":
    main()
