"""MCP server around the mock Twin. Every reading feed and actuator is a callable tool."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from mocks.twin.engine import MockTwin


def build_server(twin: MockTwin, disabled: frozenset[str] = frozenset()) -> MCPServer:
    """`disabled` hides actuator tools, to imitate a Twin that cannot expose them."""
    server = MCPServer(
        "mock-twin",
        instructions="Stand-in for the Twin layer. Follows the shared contract.",
        log_level="WARNING",
    )

    @server.tool()
    def get_topology() -> dict[str, Any]:
        """City layout: zones, adjacency, facilities, sensors, exits."""
        return twin.topology()

    @server.tool()
    def list_readings(cursor: int = 0, limit: int = 200) -> dict[str, Any]:
        """Sensor readings emitted since `cursor`, oldest first. Poll with the returned `next_cursor`."""
        return twin.list_readings(cursor, limit)

    @server.tool()
    def dispatch_unit(call: dict[str, Any]) -> dict[str, Any]:
        """Dispatch a police, ambulance or fire unit. `call` is the actuator envelope."""
        return twin.dispatch_unit(call)

    if "broadcast_alert" not in disabled:

        @server.tool()
        def broadcast_alert(call: dict[str, Any]) -> dict[str, Any]:
            """Send a public alert to one zone by SMS, siren or app. `call` is the actuator envelope."""
            return twin.broadcast_alert(call)

    if "recall_unit" not in disabled:

        @server.tool()
        def recall_unit(call: dict[str, Any]) -> dict[str, Any]:
            """Stand a dispatched unit down and return it to its station. `call` is the actuator envelope."""
            return twin.recall_unit(call)

    if "set_signal_phase" not in disabled:

        @server.tool()
        def set_signal_phase(call: dict[str, Any]) -> dict[str, Any]:
            """Hold one traffic signal in a phase (green, red, yellow, flashing) for up to an hour. `call` is the actuator envelope."""
            return twin.set_signal_phase(call)

    if "set_valve_state" not in disabled:

        @server.tool()
        def set_valve_state(call: dict[str, Any]) -> dict[str, Any]:
            """Open or close one water valve, optionally to a flow target. `call` is the actuator envelope."""
            return twin.set_valve_state(call)

    if "set_grid_connection" not in disabled:

        @server.tool()
        def set_grid_connection(call: dict[str, Any]) -> dict[str, Any]:
            """Connect or disconnect the power grid for one zone. `call` is the actuator envelope."""
            return twin.set_grid_connection(call)

    @server.tool()
    def admin_load_scenario(scenario: dict[str, Any], speed: float = 1.0) -> dict[str, Any]:
        """Mock only: start replaying a scenario."""
        return twin.load_scenario(scenario, speed)

    @server.tool()
    def admin_actuator_log() -> dict[str, Any]:
        """Mock only: every actuator call received and its result."""
        return {"calls": twin.actuator_log}

    return server
