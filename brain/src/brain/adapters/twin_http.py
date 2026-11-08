"""A Twin that speaks plain HTTP instead of MCP: the likeliest alternative a partner brings.

Same port, same envelopes, same signatures; only the carrier differs. The Twin serves:

    GET  /readings?cursor=&limit=     -> {readings, next_cursor, stream_id}   (the same page the MCP tool `list_readings` returns)
    GET  /topology                    -> the city layout
    GET  /capabilities                -> {action: description} for the actuators it really exposes
    POST /actuators/{action}          <- the signed actuator call            -> the actuator result
    POST /admin/{name}                <- (mock only) load a scenario, read the actuator log
"""

from __future__ import annotations

from typing import Any

import httpx

from brain.adapters.tls import client_context
from brain.adapters.twin_mcp import McpTwinAdapter
from brain.config import TlsConfig
from brain.ports import TwinError


class HttpTwinAdapter(McpTwinAdapter):
    """Everything above the carrier (the cursor, resuming, the stream, the calls) is the MCP adapter's; only `call_tool` and the listing differ."""

    def __init__(self, target: str | httpx.AsyncClient, poll_interval_ms: int = 200, stop_when_done: bool = False, tls: TlsConfig | None = None) -> None:
        super().__init__(target, poll_interval_ms, stop_when_done)
        self._tls = tls
        self._http: httpx.AsyncClient | None = None
        self._owned = False

    async def __aenter__(self) -> HttpTwinAdapter:
        if isinstance(self._target, httpx.AsyncClient):
            self._http = self._target
        else:
            self._http, self._owned = httpx.AsyncClient(base_url=self._target, verify=client_context(self._tls), timeout=10), True
        return self

    async def __aexit__(self, *exc: object) -> None:
        if self._http is not None and self._owned:
            await self._http.aclose()
        self._http = None

    async def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        if self._http is None:
            raise TwinError("twin adapter is not connected")
        arguments = arguments or {}
        try:
            if name == "list_readings":
                response = await self._http.get("/readings", params={"cursor": arguments.get("cursor", 0), "limit": arguments.get("limit", 200)})
            elif name == "get_topology":
                response = await self._http.get("/topology")
            elif name.startswith("admin_"):
                response = await self._http.post(f"/admin/{name[6:]}", json=arguments)
            else:
                response = await self._http.post(f"/actuators/{name}", json=arguments.get("call", arguments))
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise TwinError(f"twin {name!r} failed: {error}") from error

    async def list_capabilities(self) -> dict[str, str]:
        if self._http is None:
            raise TwinError("twin adapter is not connected")
        try:
            response = await self._http.get("/capabilities")
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise TwinError(f"twin capabilities failed: {error}") from error
