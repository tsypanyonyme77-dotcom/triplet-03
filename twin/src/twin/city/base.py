"""Seam between the Twin API and whatever simulates the city. The API layer only talks to `CitySource`."""
from __future__ import annotations

from typing import Any, Protocol

STATION_ACTUATOR_PREFIX = "dispatch-"


def station_actuator_id(station_id: str) -> str:
    """How a station is addressed as a facility (dispatch, quarantine): `police_station` -> `dispatch-police-station`."""
    return STATION_ACTUATOR_PREFIX + station_id.replace("_", "-")


class CitySource(Protocol):
    dt: float
    run_id: int
    scenario_name: str
    seed: int | None
    sim_time: float
    SCENARIOS: tuple[str, ...]

    def reset(self, scenario: str | None = None, seed: int | None = None, params: Any = None) -> None:
        """Start a scenario from t = 0 as a new run."""

    def params_dict(self) -> dict[str, Any]:
        """The city's size and risks."""

    def step(self, dt_s: float) -> list[dict[str, Any]]:
        """Advance by dt_s seconds. Return what happened, as events with `kind` and `message`."""

    def zones(self) -> list[dict[str, Any]]:
        """Zone topology: zone_id, bounds, adjacent zone ids, facilities by department code."""

    def sensor_readings(self) -> list[dict[str, Any]]:
        """Unsigned readings since the last call: sensor_id, type, zone_id, department, value."""

    def dispatch_unit(self, unit_type: str, incident_id: str, station_id: str | None = None) -> dict[str, Any]:
        """Send a unit to an incident, from `station_id` when given. Idempotent per incident and unit type."""

    def recall_unit(self, unit_id: str) -> dict[str, Any]:
        """Stand a unit down: it drives home. Idempotent; a unit at real work refuses."""

    def broadcast_alert(self, zone_id: str, channel: str, message: str) -> dict[str, Any]:
        """A public alert to everyone in a zone."""

    def stations(self) -> list[dict[str, Any]]:
        """Emergency stations: station_id, kind, unit_kind, zone_id, units."""

    def pumps(self) -> list[dict[str, Any]]:
        """Drainage pumps: pump_id, flood_zone_id, zone_id."""

    def sensors(self) -> list[dict[str, Any]]:
        """Every sensor that can send a reading: sensor_id, type, zone_id."""

    def open_incidents(self) -> list[dict[str, Any]]:
        """Call-centre incidents still open, oldest first: incident_id, zone_id, kind, units already sent."""

    def set_barrier_state(self, state: str, road_id: str | None = None, incident_id: str | None = None) -> dict[str, Any]:
        """Close or reopen a street. Idempotent."""

    def ignite_fire(self, building_id: str) -> dict[str, Any]:
        """Set a building on fire (the fire simulator). Idempotent: a building already burning is a duplicate."""

    def flood_street(self, zone_id: str) -> dict[str, Any]:
        """Block a street's drain and bring a downpour over it (the flood simulator). Idempotent."""

    def flood_state(self) -> list[dict[str, Any]]:
        """Every street's flood zone: depth, rain, drain, pump."""

    def set_pump_state(self, state: str, pump_id: str | None = None, incident_id: str | None = None) -> dict[str, Any]:
        """Start or stop a drainage pump. Idempotent."""

    def device_ids(self) -> set[str]:
        """Every device a quarantine can name."""

    def units(self) -> list[dict[str, Any]]:
        """Emergency units: type, station, status, incident, ETA."""

    def responses(self) -> list[dict[str, Any]]:
        """What the units are doing per incident."""

    def agents(self) -> list[dict[str, Any]]:
        """Pedestrians and drivers: profile, where they are going and why (empty without a decision model)."""

    def frame(self) -> dict[str, Any]:
        """The current tick, for the viewer."""

    def map(self) -> dict[str, Any]:
        """The static city, for the viewer."""
