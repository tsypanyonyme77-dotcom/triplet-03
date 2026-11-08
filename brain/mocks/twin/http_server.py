"""The mock Twin as a plain HTTP service (the same engine as the MCP mock): `python -m mocks.twin --http`."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException

from mocks.twin.engine import MockTwin

ACTIONS = {
    "dispatch_unit": "Dispatch a police, ambulance or fire unit.",
    "broadcast_alert": "Send a public alert to one zone by SMS, siren or app.",
    "recall_unit": "Stand a dispatched unit down and return it to its station.",
    "set_signal_phase": "Hold one traffic signal in a phase for up to an hour.",
    "set_valve_state": "Open or close one water valve, optionally to a flow target.",
    "set_grid_connection": "Connect or disconnect the power grid for one zone.",
}


def build_app(twin: MockTwin, disabled: frozenset[str] = frozenset()) -> FastAPI:
    app = FastAPI(title="mock Twin (HTTP)")

    @app.get("/readings")
    def readings(cursor: int = 0, limit: int = 200) -> dict[str, Any]:
        return twin.list_readings(cursor, limit)

    @app.get("/topology")
    def topology() -> dict[str, Any]:
        return twin.topology()

    @app.get("/capabilities")
    def capabilities() -> dict[str, str]:
        return {name: doc for name, doc in ACTIONS.items() if name not in disabled}

    @app.post("/actuators/{action}")
    def actuate(action: str, call: dict[str, Any]) -> dict[str, Any]:
        if action not in ACTIONS or action in disabled:
            raise HTTPException(404, f"this Twin has no actuator {action}")
        return getattr(twin, action)(call)

    @app.post("/admin/load_scenario")
    def load_scenario(body: dict[str, Any]) -> dict[str, Any]:
        return twin.load_scenario(body["scenario"], body.get("speed", 1.0))

    @app.post("/admin/actuator_log")
    def actuator_log(body: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"calls": twin.actuator_log}

    return app
