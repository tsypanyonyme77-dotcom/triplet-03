"""A Twin that publishes its readings to an MQTT broker: the proof that the partner link is replaceable.

Readings arrive on `{prefix}/{zone_id}/{type}/{sensor_id}` (QoS 1), one signed envelope per message, the same envelope MCP and HTTP carry.
Everything else (actions, topology, capabilities) goes to the Twin's HTTP address, so this class is the HTTP adapter with a different way of
receiving readings. Three things differ from polling, and each is handled here:

- **Order.** A broker keeps order per topic, not across topics, and a reconnect can redeliver. Perception refuses a `sequence_no` that is not
  above the last one seen, so a reading that overtakes its predecessor would be lost. Readings are held for `reorder_ms` and released per
  sensor in `sequence_no` order; one that is next in line goes out at once, and a gap is waited for no longer than the window.
- **Identity.** The topic is routing, not identity: the signed body is the only thing trusted, and a message whose body is not a JSON object
  is dropped and counted.
- **The end.** A real Twin never ends. A scenario run (`stop_when_done`) ends the way the polled adapters do: once the broker has gone quiet
  and every reading the mock Twin emitted has arrived, the mock says over HTTP that the scenario is done. Asked only after the Brain has handled
  the last reading, so a dispatch that makes the Twin schedule a follow-up is never cut off.

The broker client is behind `MqttTransport`, so tests run the adapter against an in-process broker and `MQTT_URL` runs it against a real one.
"""

from __future__ import annotations

import asyncio
import heapq
import json
import os
from collections.abc import AsyncIterator, Callable
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx

from brain.adapters.tls import client_context
from brain.adapters.twin_http import HttpTwinAdapter
from brain.config import MqttConfig, TlsConfig

CHECK_EVERY_S = 0.05  # how long the broker may be quiet before a scenario run asks whether the mock Twin is done


class MqttTransport(Protocol):
    """The part of a broker client the adapter needs: subscribe to some filters, then receive (topic, payload) pairs."""

    async def __aenter__(self) -> MqttTransport: ...
    async def __aexit__(self, *exc: object) -> None: ...
    async def subscribe(self, topic_filter: str, qos: int) -> None: ...
    def messages(self) -> AsyncIterator[tuple[str, bytes]]: ...


class AioMqttTransport:
    """The real broker client (`aiomqtt`, optional). On Windows it needs the selector event loop; Linux and the containers need nothing."""

    def __init__(self, config: MqttConfig) -> None:
        self._config = config
        self._client: Any = None

    async def __aenter__(self) -> AioMqttTransport:
        try:
            import aiomqtt
        except ImportError as error:
            raise RuntimeError("the mqtt adapter needs the optional package: uv sync --extra mqtt") from error
        url = urlparse(self._config.url)
        secure = url.scheme == "mqtts"
        env = os.environ
        self._client = aiomqtt.Client(
            hostname=url.hostname or "127.0.0.1", port=url.port or (8883 if secure else 1883), identifier=self._config.client_id,
            username=env.get(self._config.username_env or ""), password=env.get(self._config.password_env or ""),
            tls_context=client_context(self._config.tls) if secure else None, clean_session=False,  # a persistent session: the broker keeps QoS 1 messages while we are away
        )
        await self._client.__aenter__()
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client is not None:
            await self._client.__aexit__(*exc)
            self._client = None

    async def subscribe(self, topic_filter: str, qos: int) -> None:
        await self._client.subscribe(topic_filter, qos=qos)

    async def messages(self) -> AsyncIterator[tuple[str, bytes]]:
        async for message in self._client.messages:
            yield str(message.topic), bytes(message.payload) if isinstance(message.payload, bytes | bytearray) else str(message.payload).encode()


class ReorderBuffer:
    """Holds readings per sensor and releases them in `sequence_no` order.

    The next one in line (one above the last released, or the first ever seen from a sensor) is released at once. Others wait for the missing
    reading, and are released anyway, still in order, once they are older than the window: a lost message must not stall a sensor.
    """

    def __init__(self, window_s: float) -> None:
        self.window_s = window_s
        self._held: dict[str, list[tuple[int, int, float, dict[str, Any]]]] = {}
        self._last: dict[str, int] = {}
        self._arrivals = 0

    def add(self, reading: dict[str, Any], now: float) -> None:
        sensor, sequence = str(reading.get("sensor_id")), reading.get("sequence_no")
        if not isinstance(sequence, int) or isinstance(sequence, bool):
            sequence = -1  # perception will refuse it with a named reason; here it only has to keep its place
        self._arrivals += 1
        heapq.heappush(self._held.setdefault(sensor, []), (sequence, self._arrivals, now, reading))

    def release(self, now: float, flush: bool = False) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        for sensor, heap in self._held.items():
            while heap:
                sequence, _, arrived, reading = heap[0]
                last = self._last.get(sensor)
                if flush or last is None or sequence <= last + 1 or now - arrived >= self.window_s:
                    heapq.heappop(heap)
                    self._last[sensor] = max(sequence, last if last is not None else sequence)
                    out.append(reading)
                else:
                    break
        return out

    def next_deadline(self) -> float | None:
        """When the oldest held reading must go, or None if nothing is held."""
        arrivals = [heap[0][2] for heap in self._held.values() if heap]
        return min(arrivals) + self.window_s if arrivals else None

    @property
    def held(self) -> int:
        return sum(len(heap) for heap in self._held.values())


class MqttTwinAdapter(HttpTwinAdapter):
    def __init__(self, target: str | httpx.AsyncClient, mqtt: MqttConfig | None = None, poll_interval_ms: int = 200, stop_when_done: bool = False,
                 tls: TlsConfig | None = None, transport: Callable[[], MqttTransport] | None = None) -> None:
        super().__init__(target, poll_interval_ms, stop_when_done, tls)
        self._mqtt = mqtt or MqttConfig()
        self._open_transport = transport or (lambda: AioMqttTransport(self._mqtt))
        self._received = 0
        self.dropped = 0  # messages that were not a JSON object

    def position(self) -> dict[str, Any]:
        """How many readings were passed on. The broker, not a cursor, holds our place; the count is for the record."""
        return {"cursor": self._received, "stream_id": None}

    async def resume(self, position: dict[str, Any]) -> bool:
        """A persistent session redelivers what was missed and perception drops what it has already seen, so resuming needs no cursor."""
        self._received = int(position.get("cursor", 0))
        return True

    async def stream_readings(self) -> AsyncIterator[dict[str, Any]]:
        """Calling this again subscribes again: a persistent session means nothing sent in between is lost."""
        prefix = self._mqtt.topic_prefix.strip("/")
        loop = asyncio.get_running_loop()
        buffer = ReorderBuffer(self._mqtt.reorder_ms / 1000)
        inbox: asyncio.Queue[tuple[str, bytes] | None] = asyncio.Queue()
        async with self._open_transport() as transport:
            await transport.subscribe(f"{prefix}/+/+/+", self._mqtt.qos)

            async def pump() -> None:
                try:
                    async for item in transport.messages():
                        await inbox.put(item)
                finally:
                    await inbox.put(None)  # the connection ended

            reader = asyncio.create_task(pump())
            ended = False
            try:
                while not ended:
                    deadline = buffer.next_deadline()
                    wait = None if deadline is None else max(deadline - loop.time(), 0)
                    if self._stop_when_done:
                        wait = CHECK_EVERY_S if wait is None else min(wait, CHECK_EVERY_S)
                    try:
                        item: tuple[str, bytes] | None | tuple[()] = await asyncio.wait_for(inbox.get(), wait)
                    except TimeoutError:
                        item = ()  # quiet: a held reading's window may have run out, or a scenario may be over
                    if item is None:
                        ended = True
                    elif item:
                        reading = self._decode(item[1])
                        if reading is not None:
                            buffer.add(reading, loop.time())
                    for reading in buffer.release(loop.time(), flush=ended):
                        self._received += 1
                        yield reading
                    if not item and not ended and self._stop_when_done and not buffer.held and inbox.empty():
                        ended = await self._mock_twin_is_done()
            finally:
                reader.cancel()
                await asyncio.gather(reader, return_exceptions=True)

    async def _mock_twin_is_done(self) -> bool:
        """Mock only: has every reading the Twin emitted arrived, with nothing still scheduled? The polled adapters read the same `scenario_done`."""
        page = await self.call_tool("list_readings", {"cursor": self._received + self.dropped, "limit": 0})
        return bool(page.get("scenario_done"))

    def _decode(self, payload: bytes) -> dict[str, Any] | None:
        try:
            reading = json.loads(payload)
        except (ValueError, UnicodeDecodeError):
            reading = None
        if not isinstance(reading, dict):
            self.dropped += 1
            return None
        return reading
