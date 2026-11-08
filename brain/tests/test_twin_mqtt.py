"""The Twin over MQTT: readings by broker, the same signed envelopes, the same decisions as over MCP."""

import asyncio
import json
import os

import pytest

from brain.adapters import MqttTwinAdapter, open_twin
from brain.adapters.twin_mqtt import ReorderBuffer
from brain.config import ModelsConfig, MqttConfig, TwinConfig
from brain.scenario import inproc_partners, load_scenario, run_scenario
from mocks.twin.mqtt_publisher import InProcessBroker, topic_for

MODELS = ModelsConfig.model_validate({"embeddings": {"provider": "hashing"}})


def reading(sensor="cam-01", seq=1, zone="zone-01", kind="cctv_anomaly"):
    return {"contract_version": "1.0", "sensor_id": sensor, "type": kind, "zone_id": zone, "sequence_no": seq, "timestamp": "2026-11-05T10:00:00Z", "value": {}}


async def drain(adapter, count):
    got = []
    async for item in adapter.stream_readings():
        got.append(item)
        if len(got) == count:
            break
    return got


async def publish_after_subscribing(broker, messages, delay=0.0):
    async def run():
        await asyncio.sleep(delay)
        for topic, payload in messages:
            await broker.publish(topic, payload)
            await asyncio.sleep(0)
        broker.close()

    started = []
    broker.on_subscribe = lambda: None if started else started.append(asyncio.get_running_loop().create_task(run()))


def adapter_for(broker, **options):
    return MqttTwinAdapter("http://twin", MqttConfig(**options), transport=broker.transport)


def decisions(result):
    return sorted(json.dumps({"action": e.data["action"], "actuator_id": e.data["actuator_id"], "params": e.data["params"]}, sort_keys=True)
                  for e in result.sink.of("brain.decision.made"))


async def test_readings_arrive_through_the_broker_unchanged():
    broker, sent = InProcessBroker(), reading()
    await publish_after_subscribing(broker, [(topic_for("city", sent), json.dumps(sent).encode())])

    assert [r async for r in adapter_for(broker).stream_readings()] == [sent]


async def test_a_reading_arriving_late_is_reordered_by_sequence_no():
    broker = InProcessBroker()
    one, two, three = (reading(seq=n) for n in (1, 2, 3))
    await publish_after_subscribing(broker, [(topic_for("city", r), json.dumps(r).encode()) for r in (one, three, two)])

    got = [r async for r in adapter_for(broker, reorder_ms=500).stream_readings()]

    assert [r["sequence_no"] for r in got] == [1, 2, 3]


async def test_a_lost_reading_does_not_stall_the_sensor_longer_than_the_window():
    broker = InProcessBroker()
    one, three = reading(seq=1), reading(seq=3)  # 2 never comes
    await publish_after_subscribing(broker, [(topic_for("city", r), json.dumps(r).encode()) for r in (one, three)])

    got = [r async for r in adapter_for(broker, reorder_ms=30).stream_readings()]

    assert [r["sequence_no"] for r in got] == [1, 3]


async def test_one_sensor_waiting_for_a_gap_does_not_hold_another_sensor_back():
    broker = InProcessBroker()
    a1, a3, b1 = reading("cam-a", 1), reading("cam-a", 3), reading("cam-b", 1)
    await publish_after_subscribing(broker, [(topic_for("city", r), json.dumps(r).encode()) for r in (a1, a3, b1)])

    got = [(r["sensor_id"], r["sequence_no"]) async for r in adapter_for(broker, reorder_ms=40).stream_readings()]

    assert got.index(("cam-b", 1)) < got.index(("cam-a", 3))


async def test_a_message_that_is_not_a_json_object_is_dropped_and_counted():
    broker, good = InProcessBroker(), reading()
    await publish_after_subscribing(broker, [("city/zone-01/cctv_anomaly/cam-01", b"not json"), ("city/zone-01/cctv_anomaly/cam-01", b"[1, 2]"), (topic_for("city", good), json.dumps(good).encode())])
    adapter = adapter_for(broker)

    got = [r async for r in adapter.stream_readings()]

    assert got == [good] and adapter.dropped == 2


async def test_the_topic_is_routing_and_the_signed_body_is_the_identity():
    broker, body = InProcessBroker(), reading("cam-real", 1, "zone-01")
    await publish_after_subscribing(broker, [("city/zone-09/cctv_anomaly/cam-claimed", json.dumps(body).encode())])

    got = [r async for r in adapter_for(broker).stream_readings()]

    assert got[0]["sensor_id"] == "cam-real"  # nothing from the topic is copied into the reading


async def test_the_d3_city_over_mqtt_decides_as_d3():
    over_mcp = await run_scenario(load_scenario("t14"), inproc_partners(), models=MODELS, speed=0, timeout_s=30)
    over_mqtt = await run_scenario(load_scenario("t14"), inproc_partners(), models=MODELS, speed=0, timeout_s=30)

    assert over_mqtt.passed and over_mcp.passed
    assert decisions(over_mqtt) == decisions(over_mcp)


async def test_a_message_published_while_the_brain_is_away_is_waiting_when_it_returns():
    broker, first, second = InProcessBroker(), reading(seq=1), reading(seq=2)
    await publish_after_subscribing(broker, [(topic_for("city", first), json.dumps(first).encode())])
    adapter = adapter_for(broker)
    assert [r["sequence_no"] for r in [r async for r in adapter.stream_readings()]] == [1]

    await broker.publish(topic_for("city", second), json.dumps(second).encode())  # nobody is connected
    broker.on_subscribe = None
    broker.close()

    assert [r["sequence_no"] for r in [r async for r in adapter_for(broker).stream_readings()]] == [2]


async def test_a_wrong_topic_prefix_delivers_nothing():
    broker, sent = InProcessBroker(), reading()
    await publish_after_subscribing(broker, [(topic_for("elsewhere", sent), json.dumps(sent).encode())])

    assert [r async for r in adapter_for(broker).stream_readings()] == []


def test_the_reorder_buffer_releases_the_next_in_line_at_once_and_a_gap_after_the_window():
    buffer = ReorderBuffer(0.2)
    buffer.add(reading(seq=1), 0.0)
    assert [r["sequence_no"] for r in buffer.release(0.0)] == [1]
    buffer.add(reading(seq=3), 0.1)
    assert buffer.release(0.15) == [] and buffer.next_deadline() == pytest.approx(0.3)
    assert [r["sequence_no"] for r in buffer.release(0.31)] == [3]


def test_the_adapter_in_config_picks_the_broker():
    assert type(open_twin(TwinConfig(adapter="mqtt", url="http://twin:9000"))).__name__ == "MqttTwinAdapter"


@pytest.mark.skipif("MQTT_URL" not in os.environ, reason="needs a broker: MQTT_URL=mqtt://127.0.0.1:1883 (docker compose --profile mqtt up mosquitto)")
async def test_the_b2_city_over_a_real_broker_decides_as_b2():
    from urllib.parse import urlparse

    import aiomqtt

    from mocks.twin.mqtt_publisher import drive

    url = urlparse(os.environ["MQTT_URL"])
    scenario = load_scenario("t14")
    async with inproc_partners(transport="http") as (twin_http, guardian):
        await guardian.post("/admin/config", json=scenario.get("guardian", {}))
        # The adapter subscribes first, then the publisher starts: a broker holds nothing for a subscriber that is not there yet.
        adapter = MqttTwinAdapter(twin_http, MqttConfig(url=os.environ["MQTT_URL"], reorder_ms=50, client_id="brain-test"), stop_when_done=True)
        await adapter.__aenter__()  # the HTTP side must be connected before it can load a scenario
        playable = {key: scenario[key] for key in ("id", "topology", "events", "on_dispatch") if key in scenario}
        await adapter.call_tool("admin_load_scenario", {"scenario": playable, "speed": 0})

        async def publish():
            await asyncio.sleep(0.5)
            async with aiomqtt.Client(url.hostname, url.port or 1883) as client:
                async def page(cursor):
                    return (await adapter.call_tool("list_readings", {"cursor": cursor, "limit": 200}))

                async def send(topic, payload):
                    await client.publish(topic, payload, qos=1)

                await drive(page, send)

        task = asyncio.create_task(publish())
        got = [r async for r in adapter.stream_readings()]
        task.cancel()  # `drive` runs until cancelled: a dispatch can make the Twin schedule more readings
        await asyncio.gather(task, return_exceptions=True)
        await adapter.__aexit__(None, None, None)

    assert got and all("sensor_id" in r for r in got)
