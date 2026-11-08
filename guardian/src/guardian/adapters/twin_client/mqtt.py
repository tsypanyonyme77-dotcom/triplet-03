"""MQTT TwinClient (optional `aiomqtt`, imported lazily): subscribe to readings, publish tool calls and wait
for the reply on <tools_topic>/<name>/reply/<call_id>."""

from __future__ import annotations

import asyncio
import json
from typing import Any

from guardian.adapters.twin_client.base import OnReadings, TwinUnavailable
from guardian.clock import Clock
from guardian.config import TwinCfg


class MqttTwinClient:
    transport = "mqtt"

    def __init__(self, cfg: TwinCfg, clock: Clock) -> None:
        try:
            import aiomqtt  # noqa: F401
        except ImportError as e:
            raise RuntimeError("twin.transport=mqtt needs the optional dependency: pip install 'guardian[mqtt]'") from e
        self.cfg, self.clock = cfg, clock
        assert cfg.mqtt is not None  # enforced by config validation
        self.section = cfg.mqtt
        self.connected = False

    def _client(self) -> Any:
        import aiomqtt

        return aiomqtt.Client(self.section.host, self.section.port)

    async def call_tool(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        topic = f"{self.section.tools_topic}/{name}"
        reply_topic = f"{topic}/reply/{payload.get('call_id', '')}"
        try:
            async with self._client() as client:
                await client.subscribe(reply_topic)
                await client.publish(topic, json.dumps(payload))
                async with asyncio.timeout(self.cfg.timeout_s):
                    async for msg in client.messages:
                        body = json.loads(msg.payload)
                        if isinstance(body, dict):
                            return body
        except Exception as e:
            raise TwinUnavailable(f"mqtt tool {name} failed: {e}") from e
        raise TwinUnavailable(f"mqtt tool {name}: no reply")

    async def health(self) -> bool:
        return self.connected

    async def run_ingest(self, on_readings: OnReadings) -> None:
        while True:
            try:
                async with self._client() as client:
                    await client.subscribe(self.section.readings_topic)
                    self.connected = True
                    async for msg in client.messages:
                        try:
                            body = json.loads(msg.payload)
                        except ValueError:
                            body = {"_raw": str(msg.payload)[:200]}
                        await on_readings(body if isinstance(body, list) else [body])
            except Exception:
                self.connected = False
                await self.clock.sleep(self.cfg.poll_interval_s)

    async def close(self) -> None:
        return None
