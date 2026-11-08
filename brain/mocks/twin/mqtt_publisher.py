"""Publishes the mock Twin's readings to an MQTT broker, so the Brain can be run over MQTT (scenario b38).

    python -m mocks.twin.mqtt_publisher --twin-url http://twin:8765 --mqtt-url mqtt://mosquitto:1883

Two ways to use it. `drive` takes any coroutine that publishes a topic and a payload, which is how tests and `--inproc` runs use it with
`InProcessBroker`. The command line polls a running mock Twin (`python -m mocks.twin --http`) and publishes to a real broker.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

Publish = Callable[[str, bytes], Awaitable[None]]


def topic_for(prefix: str, reading: dict[str, Any]) -> str:
    return f"{prefix}/{reading['zone_id']}/{reading['type']}/{reading['sensor_id']}"


async def drive(page: Callable[[int], Awaitable[dict[str, Any]]], publish: Publish, prefix: str = "city", poll_s: float = 0.01, until_done: bool = False) -> int:
    """Pull the Twin's pages and publish each reading. Runs until cancelled, because a dispatch can make the Twin schedule more readings later;
    with `until_done` it returns once the scenario is done. Returns how many readings went out."""
    cursor = 0
    while True:
        batch = await page(cursor)
        for reading in batch["readings"]:
            await publish(topic_for(prefix, reading), json.dumps(reading).encode())
        cursor = batch["next_cursor"]
        if not batch["readings"]:
            if until_done and batch.get("scenario_done"):
                return cursor
            await asyncio.sleep(poll_s)


class InProcessBroker:
    """The smallest broker that behaves like one for this purpose: topic filters with `+` and `#`, and a persistent session per client, so a
    message published while the client is away is waiting when it subscribes again (QoS 1 with `clean_session=False`)."""

    def __init__(self) -> None:
        self._sessions: dict[str, tuple[list[str], asyncio.Queue[tuple[str, bytes] | None]]] = {}
        self.on_subscribe: Callable[[], None] | None = None  # called after a subscription, so a publisher can start once someone listens

    @staticmethod
    def matches(topic_filter: str, topic: str) -> bool:
        wanted, actual = topic_filter.split("/"), topic.split("/")
        for index, part in enumerate(wanted):
            if part == "#":
                return True
            if index >= len(actual) or (part != "+" and part != actual[index]):
                return False
        return len(wanted) == len(actual)

    async def publish(self, topic: str, payload: bytes) -> None:
        for filters, queue in self._sessions.values():
            if any(self.matches(topic_filter, topic) for topic_filter in filters):
                queue.put_nowait((topic, payload))

    def close(self) -> None:
        """End every client's connection after what is already queued (a real client sees its connection drop)."""
        for _, queue in self._sessions.values():
            queue.put_nowait(None)

    def session(self, client_id: str) -> tuple[list[str], asyncio.Queue[tuple[str, bytes] | None]]:
        return self._sessions.setdefault(client_id, ([], asyncio.Queue()))

    def transport(self, client_id: str = "city-brain") -> InProcessTransport:
        return InProcessTransport(self, client_id)


class InProcessTransport:
    """An `MqttTransport` onto an `InProcessBroker`."""

    def __init__(self, broker: InProcessBroker, client_id: str) -> None:
        self._broker, self._client_id = broker, client_id

    async def __aenter__(self) -> InProcessTransport:
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None  # the session stays: messages keep queueing for the next connection

    async def subscribe(self, topic_filter: str, qos: int) -> None:
        filters, _ = self._broker.session(self._client_id)
        if topic_filter not in filters:
            filters.append(topic_filter)
        if self._broker.on_subscribe is not None:
            self._broker.on_subscribe()

    async def messages(self) -> AsyncIterator[tuple[str, bytes]]:
        _, queue = self._broker.session(self._client_id)
        while True:
            item = await queue.get()
            if item is None:
                return
            yield item


async def publish_to_broker(twin_url: str, mqtt_url: str, prefix: str = "city") -> int:
    """The command line's job: poll a running mock Twin over HTTP and publish to a real broker."""
    from urllib.parse import urlparse

    import aiomqtt
    import httpx

    url = urlparse(mqtt_url)
    async with httpx.AsyncClient(base_url=twin_url, timeout=10) as http, aiomqtt.Client(url.hostname or "127.0.0.1", url.port or 1883) as client:
        async def page(cursor: int) -> dict[str, Any]:
            response = await http.get("/readings", params={"cursor": cursor, "limit": 200})
            response.raise_for_status()
            return response.json()

        async def publish(topic: str, payload: bytes) -> None:
            await client.publish(topic, payload, qos=1)

        return await drive(page, publish, prefix, until_done=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Publish a mock Twin's readings to an MQTT broker")
    parser.add_argument("--twin-url", default="http://127.0.0.1:8765")
    parser.add_argument("--mqtt-url", default="mqtt://127.0.0.1:1883")
    parser.add_argument("--prefix", default="city")
    args = parser.parse_args()
    print(f"published {asyncio.run(publish_to_broker(args.twin_url, args.mqtt_url, args.prefix))} readings")


if __name__ == "__main__":
    main()
