"""TwinPort over MCP: the Twin exposes each reading feed and each actuator as a tool.

`target` is a Streamable HTTP URL, or an in-process MCPServer (used by tests and `--inproc`).

Tool conventions this adapter expects (see INTERFACE.md):
  get_topology()                      -> {zones, adjacency, facilities, sensors, exits}
  list_readings(cursor, limit)        -> {readings: [...], next_cursor: int}
  <action>(call=<actuator envelope>)  -> action result, e.g. dispatch_unit
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

from mcp import Client

from brain.contracts import ActuatorCall, ActuatorResult
from brain.ports import TwinError

READ_TOOLS = {"get_topology", "list_readings"}


class McpTwinAdapter:
    def __init__(self, target: Any, poll_interval_ms: int = 200, stop_when_done: bool = False) -> None:
        self._target = target
        self._poll_s = poll_interval_ms / 1000
        self._stop_when_done = stop_when_done
        self._client: Client | None = None
        self._cursor = 0
        self._stream_id: str | None = None

    async def __aenter__(self) -> McpTwinAdapter:
        self._client = Client(self._target)
        await self._client.__aenter__()
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._client is not None:
            await self._client.__aexit__(*exc)
            self._client = None

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._client is None:
            raise TwinError("twin adapter is not connected")
        try:
            result = await self._client.call_tool(name, arguments or {})
        except Exception as error:
            raise TwinError(f"twin tool {name!r} failed: {error}") from error
        text = result.content[0].text if result.content else ""
        if result.is_error:
            raise TwinError(f"twin tool {name!r} returned an error: {text}")
        if result.structured_content is not None:
            return result.structured_content
        try:
            return json.loads(text)
        except json.JSONDecodeError as error:
            raise TwinError(f"twin tool {name!r} returned non-JSON content: {text[:200]!r}") from error

    def position(self) -> dict[str, Any]:
        """Where this adapter is in the Twin's stream, in a form that can be saved."""
        return {"cursor": self._cursor, "stream_id": self._stream_id}

    async def resume(self, position: dict[str, Any]) -> bool:
        """Continue from a saved position. False if the Twin has started a new stream since.

        A Twin that sends no `stream_id` cannot be checked, and the saved cursor is trusted.
        """
        page = await self.call_tool("list_readings", {"cursor": int(position.get("cursor", 0)), "limit": 0})
        current, saved = page.get("stream_id"), position.get("stream_id")
        if current and saved and current != saved:
            return False
        self._cursor, self._stream_id = int(position.get("cursor", 0)), current or saved
        return True

    async def get_topology(self) -> dict[str, Any]:
        return await self.call_tool("get_topology")

    async def list_capabilities(self) -> dict[str, str]:
        if self._client is None:
            raise TwinError("twin adapter is not connected")
        tools = await self._client.list_tools()
        return {
            t.name: (t.description or "").strip()
            for t in tools.tools
            if t.name not in READ_TOOLS and not t.name.startswith("admin_")
        }

    async def call_actuator(self, call: ActuatorCall) -> ActuatorResult:
        result = await self.call_tool(call.action, {"call": call.model_dump(mode="json")})
        return ActuatorResult.model_validate(result)

    async def stream_readings(self) -> AsyncIterator[dict[str, Any]]:
        """Calling this again resumes after the last reading already yielded."""
        while True:
            page = await self.call_tool("list_readings", {"cursor": self._cursor, "limit": 200})
            self._stream_id = page.get("stream_id", self._stream_id)
            readings = page.get("readings", [])
            for reading in readings:
                self._cursor += 1
                yield reading
            if not readings:
                # `scenario_done` is a mock-only hint; a real Twin never sets it.
                if self._stop_when_done and page.get("scenario_done"):
                    return
                await asyncio.sleep(self._poll_s)
