"""MQTT taşıma katmanı (paho-mqtt 2.x): simülatör yayıncısı ve alım aboneliği.

Kimlik bilgileri yalnız ortam değişkeninden okunur; koda varsayılan parola gömülmez (CLAUDE.md §2.2):

- simülatör: `MQTT_SIM_USER`, `MQTT_SIM_PASS`
- alım:      `MQTT_INGEST_USER`, `MQTT_INGEST_PASS`

`--anonymous` yalnız yerel geliştirme aracısı (127.0.0.1, amqtt) içindir. Yayıncı yalnız `telemetry` ve `status`
konularına yazabilir (`schema.topic_for`); sunucudaki ACL de bunu zorlar.
"""

import os
from typing import Callable, Optional

import paho.mqtt.client as mqtt

from twin.devices.schema import TOPIC_ROOT, Telemetry, topic_for

SUBSCRIPTIONS = [(f"{TOPIC_ROOT}/+/telemetry", 1), (f"{TOPIC_ROOT}/+/status", 1)]


def credentials(prefix: str, anonymous: bool) -> Optional[tuple]:
    if anonymous:
        return None
    user, pw = os.environ.get(f"{prefix}_USER"), os.environ.get(f"{prefix}_PASS")
    if not user or not pw:
        raise RuntimeError(
            f"{prefix}_USER ve {prefix}_PASS ortam değişkenleri gerekli (yerel test aracısı için --anonymous)"
        )
    return user, pw


def _client(client_id: str, creds: Optional[tuple]) -> mqtt.Client:
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, clean_session=True)
    if creds:
        c.username_pw_set(*creds)
    return c


class Publisher:
    def __init__(self, host: str, port: int, creds: Optional[tuple], client_id: str = "twin-devsim"):
        self.client = _client(client_id, creds)
        self.client.connect(host, port, keepalive=60)
        self.client.loop_start()

    def telemetry(self, t: Telemetry) -> None:
        payload = t.model_dump_json(by_alias=True, exclude_none=True)
        self.client.publish(topic_for(t.node, "telemetry"), payload, qos=1).wait_for_publish(10)

    def status(self, node: str, state: str) -> None:
        self.client.publish(topic_for(node, "status"), state, qos=1, retain=True).wait_for_publish(10)

    def close(self) -> None:
        self.client.loop_stop()
        self.client.disconnect()


def subscribe_forever(
    host: str,
    port: int,
    creds: Optional[tuple],
    on_message: Callable[[str, bytes], None],
    client_id: str = "twin-ingest",
    on_tick: Optional[Callable[[], None]] = None,
    tick_s: float = 60.0,
) -> None:
    """Telemetri ve durum konularına abone olur; `on_tick` her `tick_s` saniyede çağrılır (çevrimdışı denetimi)."""
    import time

    c = _client(client_id, creds)

    def _on_connect(client, userdata, flags, reason_code, properties):
        client.subscribe(SUBSCRIPTIONS)

    def _on_message(client, userdata, msg):
        on_message(msg.topic, msg.payload)

    c.on_connect = _on_connect
    c.on_message = _on_message
    c.connect(host, port, keepalive=60)
    c.loop_start()
    try:
        while True:
            time.sleep(tick_s)
            if on_tick:
                on_tick()
    finally:
        c.loop_stop()
        c.disconnect()
