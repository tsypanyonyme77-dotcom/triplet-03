"""The city layout in the City Brain's shape (`get_topology`): zones, adjacency, exits, facilities, sensors.

Facilities are what a dispatcher can address: each emergency station is one, with its own
`actuator_id` (`dispatch-<station>`), so the City Brain can choose the station a unit comes from, and the
Guardian can quarantine one station without stopping the others. The drainage pumps are facilities too.
"""
from __future__ import annotations

from typing import Any

from twin.actuators import PUMP_ACTUATOR_ID
from twin.city.base import CitySource, station_actuator_id
from twin.contract import CONTRACT_VERSION


def station_of(city: CitySource, actuator_id: str) -> dict[str, Any] | None:
    """The station a facility actuator id names, or None."""
    return next((s for s in city.stations() if station_actuator_id(s["station_id"]) == actuator_id), None)


def facilities(city: CitySource) -> list[dict[str, Any]]:
    stations = [{"id": s["station_id"], "type": s["kind"], "zone_id": s["zone_id"], "actuator_id": station_actuator_id(s["station_id"]),
                 "units": s["units"], "unit_type": s["unit_kind"], "location": s["location"]} for s in city.stations()]
    pumps = [{"id": p["pump_id"], "type": "drainage_pump", "zone_id": p["zone_id"], "actuator_id": PUMP_ACTUATOR_ID,
              "flood_zone_id": p["flood_zone_id"]} for p in city.pumps()]
    return stations + pumps


def topology(city: CitySource) -> dict[str, Any]:
    zones = city.zones()
    pairs = sorted({tuple(sorted((z["zone_id"], other))) for z in zones for other in z["adjacent"]})
    return {
        "contract_version": CONTRACT_VERSION,
        "zones": [{"id": z["zone_id"], "name": z["name"],
                   "x": round((z["bounds_m"]["x_min"] + z["bounds_m"]["x_max"]) / 2, 1),
                   "y": round((z["bounds_m"]["y_min"] + z["bounds_m"]["y_max"]) / 2, 1),
                   "bounds_m": z["bounds_m"]} for z in zones],
        "adjacency": [list(p) for p in pairs],
        "exits": [z["zone_id"] for z in zones if z.get("exit")],
        "facilities": facilities(city),
        "sensors": [{"id": s["sensor_id"], "type": s["type"], "zone_id": s["zone_id"]} for s in city.sensors()],
    }
