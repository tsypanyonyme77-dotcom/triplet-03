"""MCP TwinClient (optional `mcp` SDK, imported lazily): Twin tools are MCP tools; readings via a pull tool."""

from __future__ import annotations

import json
from typing import Any

from guardian.adapters.twin_client.base import OnReadings, TwinUnavailable
from guardian.clock import Clock
from guardian.config import TwinCfg


class McpTwinClient:
    transport = "mcp"

    def __init__(self, cfg: TwinCfg, clock: Clock) -> None:
        try:
            from mcp import ClientSession  # noqa: F401
            from mcp.client.streamable_http import streamablehttp_client  # noqa: F401
        except ImportError as e:
            raise RuntimeError("twin.transport=mcp needs the optional dependency: pip install 'guardian[mcp]'") from e
        self.cfg, self.clock = cfg, clock
        assert cfg.mcp is not None  # enforced by config validation
        self.section = cfg.mcp

    async def _call(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client

        try:
            async with streamablehttp_client(self.section.url) as (read, write, _), \
                    ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(name, args)
        except Exception as e:
            raise TwinUnavailable(f"mcp tool {name} failed: {e}") from e
        for block in result.content:
            text = getattr(block, "text", None)
            if text:
                body = json.loads(text)
                if isinstance(body, dict):
                    return body
        raise TwinUnavailable(f"mcp tool {name} returned no JSON object")

    async def call_tool(self, name: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self._call(name, payload)

    async def health(self) -> bool:
        try:
            await self._call(self.section.readings_tool, {"cursor": -1})
            return True
        except TwinUnavailable:
            return False

    async def run_ingest(self, on_readings: OnReadings) -> None:
        cursor = 0
        while True:
            try:
                body = await self._call(self.section.readings_tool, {"cursor": cursor})
                cursor = int(body.get("cursor", cursor))
                if body.get("readings"):
                    await on_readings(body["readings"])
            except TwinUnavailable:
                pass
            await self.clock.sleep(self.cfg.poll_interval_s)

    async def close(self) -> None:
        return None
