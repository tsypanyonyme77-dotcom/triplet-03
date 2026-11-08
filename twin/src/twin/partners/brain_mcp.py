"""The City Brain's default carrier: MCP over Streamable HTTP at /mcp (its `twin.adapter: mcp`).

Tools, as the City Brain's adapter expects them:
  get_topology()                  -> zones, adjacency, exits, facilities, sensors
  list_readings(cursor, limit)    -> {readings, next_cursor, stream_id}
  <action>(call)                  -> the actuator's result, one tool per action offered (its tool list is its capability list)
The tools call the same code as the HTTP routes (brain_http.py). A refused call is a tool error.

MCP checks the Host header against DNS rebinding. Inside Docker the City Brain reaches us as `twin:8001`,
so the allowed hosts come from configuration (TWIN_MCP_ALLOWED_HOSTS).
"""
from __future__ import annotations

from typing import Any, Callable

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette

from twin.actuation import CallRefused
from twin.city.base import CitySource
from twin.partners.brain_calls import BrainDoor, capabilities
from twin.partners.reading_log import MAX_PAGE, ReadingLog
from twin.partners.topology import topology


def _actuator_tool(door: BrainDoor, action: str) -> Callable[..., dict[str, Any]]:
    def tool(call: dict[str, Any]) -> dict[str, Any]:
        try:
            return door.handle(action, call)
        except CallRefused as exc:
            raise ToolError(f"{exc.status_code}: {exc.detail}") from exc
    return tool


def brain_mcp_server(log: ReadingLog, city: CitySource, door: BrainDoor) -> MCPServer:
    server = MCPServer("twin", instructions="The Twin layer: the city's signed sensor readings, its layout, and its actuators.")

    def get_topology() -> dict[str, Any]:
        return topology(city)

    def list_readings(cursor: int = 0, limit: int = 200) -> dict[str, Any]:
        try:
            return log.page(cursor, min(limit, MAX_PAGE))
        except ValueError as exc:
            raise ToolError(str(exc)) from exc

    server.add_tool(get_topology, name="get_topology",
                    description="The city layout: zones (with adjacency and exits), facilities (stations and pumps, with the "
                                "actuator_id to address them) and sensors.")
    server.add_tool(list_readings, name="list_readings",
                    description="Signed sensor readings from `cursor` on, oldest first: {readings, next_cursor, stream_id}. "
                                "`stream_id` changes when the Twin restarts.")
    for action, description in capabilities().items():
        server.add_tool(_actuator_tool(door, action), name=action,
                        description=f"{description} Argument `call`: the signed actuator call envelope.")
    return server


def mcp_app(server: MCPServer, allowed_hosts: list[str]) -> Starlette:
    """The Streamable HTTP app, endpoint /mcp. Its session manager must run inside the host app's lifespan."""
    security = TransportSecuritySettings(enable_dns_rebinding_protection=bool(allowed_hosts), allowed_hosts=allowed_hosts,
                                         allowed_origins=[f"http://{h}" for h in allowed_hosts])
    return server.streamable_http_app(transport_security=security)
