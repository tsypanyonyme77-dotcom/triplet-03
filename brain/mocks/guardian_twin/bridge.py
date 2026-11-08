"""The Guardian team's Twin mock, spoken to as the Brain's Twin port (`twin.adapter: http`).

Their Twin mock pushes signed 1.0 readings to the Guardian and offers `GET /readings?cursor=` and `POST /tools/{name}`. It has no `/topology`
and no `/capabilities`, names its cursor `cursor` and has no stream id, and it does not know `broadcast_alert` or `recall_unit`, so the Brain
cannot start against it. This bridge fills exactly those gaps and nothing else; the readings pass through untouched (same signature, same dialect).

    GET  /readings          their page, with `next_cursor` and a `stream_id`
    GET  /topology          built from the Guardian's own config (city_model, crosschecks, policies) plus the sensors seen on the stream
    GET  /capabilities      the six actions the Brain may ask for
    POST /actuators/{a}     broadcast_alert: the mock Twin's own engine (checks the Brain's signature, answers duplicates). recall_unit: accepted
                            when signed. The four audited actions go through the Guardian (`guardian.gateway`), never here.

shortcut: `limit` is ignored (their page has no limit) and `stream_id` is this process's start, so restart the bridge with their Twin mock; upgrade when
the Twin team's Twin has a real stream id.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import httpx
import yaml
from fastapi import FastAPI, HTTPException

from mocks.twin.engine import MockTwin

ACTIONS = {
    "dispatch_unit": "Dispatch a police, ambulance or fire unit (through the Guardian).",
    "broadcast_alert": "Send a public alert to one zone by SMS, siren or app.",
    "recall_unit": "Stand a dispatched unit down and return it to its station.",
    "set_signal_phase": "Hold one traffic signal in a phase (through the Guardian).",
    "set_valve_state": "Open or close one water valve (through the Guardian).",
    "set_grid_connection": "Connect or disconnect the power grid for one zone (through the Guardian).",
}
# The Guardian knows one dispatcher (`dispatch-central`); the Brain picks a station by unit type. These are the Brain's stations: with
# `guardian.dispatcher_id` set, every dispatch is sent to the one dispatcher and names its station in `params.station_id`.
STATIONS = [("police_station", "ps-07", "zone-07", "police-dispatch-07"), ("fire_station", "fs-08", "zone-08", "fire-dispatch-08"),
            ("hospital", "hosp-03", "zone-03", "ambulance-dispatch-03")]
FACILITY_TYPE = {"valve": "valve", "grid_switch": "grid_breaker", "traffic_signal": "signal_controller"}  # the Guardian's actuator types, as the Brain names them


def topology(config_dir: Path, sensors: list[dict[str, str]]) -> dict[str, Any]:
    """The Brain's view of the Guardian's city: its zones and adjacency, the actuators in its registry, the sensors the stream has shown."""
    zones = yaml.safe_load((config_dir / "city_model.yaml").read_text())["zones"]
    adjacency = yaml.safe_load((config_dir / "crosschecks.yaml").read_text())["adjacency"]
    actuators = yaml.safe_load((config_dir / "policies.yaml").read_text())["actuators"]
    ids = list(zones)
    facilities = [{"id": a, "type": FACILITY_TYPE[v["type"]], "zone_id": v["zone_id"], "actuator_id": a}
                  for a, v in actuators.items() if v["type"] in FACILITY_TYPE and v.get("zone_id") in zones]
    facilities += [{"id": i, "type": t, "zone_id": z, "actuator_id": a, "units": 2} for t, i, z, a in STATIONS if z in zones]
    return {
        "zones": [{"id": z, "name": zones[z].get("type", z), "x": n % 2, "y": n // 2} for n, z in enumerate(ids)],
        "adjacency": sorted({tuple(sorted((a, b))) for a, near in adjacency.items() for b in near if a in zones and b in zones}),
        "exits": [z for z in ids if zones[z].get("road_access")][:1],
        "facilities": facilities,
        "sensors": sensors,
    }


def build_app(upstream: httpx.AsyncClient, twin: MockTwin, config_dir: Path) -> FastAPI:
    app, stream_id = FastAPI(title="Guardian team's Twin mock, as the Brain's Twin"), uuid.uuid4().hex[:8]

    async def page(cursor: int) -> dict[str, Any]:
        try:
            response = await upstream.get("/readings", params={"cursor": cursor})
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as error:
            raise HTTPException(502, f"the Twin mock did not answer: {error}") from error

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readings")
    async def readings(cursor: int = 0, limit: int = 200) -> dict[str, Any]:
        body = await page(cursor)
        return {"readings": body.get("readings", []), "next_cursor": body.get("cursor", cursor), "stream_id": stream_id}

    @app.get("/topology")
    async def get_topology() -> dict[str, Any]:
        seen = {r["sensor_id"]: {"id": r["sensor_id"], "type": r["sensor_type"], "zone_id": r["zone_id"]} for r in (await page(0)).get("readings", [])}
        return topology(config_dir, sorted(seen.values(), key=lambda s: s["id"]))

    @app.get("/capabilities")
    def capabilities() -> dict[str, str]:
        return ACTIONS

    @app.post("/actuators/{action}")
    def actuate(action: str, call: dict[str, Any]) -> dict[str, Any]:
        if action == "broadcast_alert":
            return twin.broadcast_alert(call)
        if action == "recall_unit":
            envelope, problem = twin._accept(call, "recall_unit")  # shortcut: their Twin has no units to recall; a signed call is answered as recalled
            return {"status": "rejected", "reason": problem} if envelope is None else {"status": "recalled", "unit_id": envelope.params.get("unit_id")}
        raise HTTPException(404, f"{action} goes through the Guardian (guardian.gateway), not the Twin")

    return app
