"""TwinClient protocol and the factory that picks a transport from guardian.yaml."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from guardian.clock import Clock
from guardian.config import TwinCfg

OnReadings = Callable[[list[dict[str, Any]]], Awaitable[None]]


class TwinUnavailable(RuntimeError):
    pass


class TwinClient(Protocol):
    transport: str

    async def call_tool(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        """Invoke an actuator/containment tool; returns the Twin reply. Raises TwinUnavailable."""
        ...

    async def health(self) -> bool: ...

    async def run_ingest(self, on_readings: OnReadings) -> None:
        """Pull/subscribe mode: feed raw envelopes to the pipeline until cancelled."""
        ...

    async def close(self) -> None: ...


def make_twin_client(cfg: TwinCfg, clock: Clock, http_client: Any = None) -> TwinClient:
    if cfg.transport == "rest":
        from guardian.adapters.twin_client.http import HttpTwinClient

        return HttpTwinClient(cfg, clock, http_client)
    if cfg.transport == "mcp":
        from guardian.adapters.twin_client.mcp import McpTwinClient

        return McpTwinClient(cfg, clock)
    from guardian.adapters.twin_client.mqtt import MqttTwinClient

    return MqttTwinClient(cfg, clock)
