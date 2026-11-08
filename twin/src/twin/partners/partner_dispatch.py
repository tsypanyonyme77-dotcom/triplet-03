"""A partner's dispatch in our terms, shared by the City Brain's door and the Guardian's (which forwards the
City Brain's dispatches): the station it addressed, its incident linked to ours, and the unit remembered
so that its unit_status readings carry the partner's incident id."""
from __future__ import annotations

from typing import Any

from twin.actuation import Actuation, CallRefused
from twin.actuators import ACTUATORS
from twin.city.base import CitySource
from twin.contract import ActuatorCall
from twin.events import EventLog
from twin.partners.incident_links import IncidentLinks
from twin.partners.topology import station_of


def refused_result(events: EventLog, who: str, action: str, reason: str, extra: dict[str, Any]) -> dict[str, Any]:
    events.emit("actuator_rejected", f"{who} {action} rejected: {reason}", **{**extra, "action": action, "reason": reason})
    return {"status": "rejected", "reason": reason, **extra}


def run(actuation: Actuation, call: ActuatorCall) -> dict[str, Any]:
    """Runs our call and returns the actuator's result, flat."""
    response = actuation.execute(call)
    return {**response["result"], **({"replayed": True} if response.get("replayed") else {})}


def dispatch(actuation: Actuation, city: CitySource, links: IncidentLinks, events: EventLog, *, who: str,
             addressed_to: str | None, params: dict[str, Any], partner_incident: Any, common: dict[str, Any]) -> dict[str, Any]:
    """`addressed_to`: a station's facility id, our dispatch centre's id, or None (any station).
    `common`: the ActuatorCall fields other than actuator_id and params."""
    our_centre = ACTUATORS["dispatch_unit"]["actuator_id"]
    station = station_of(city, addressed_to) if addressed_to else None
    if addressed_to and station is None and addressed_to != our_centre:
        raise CallRefused(400, f"'{addressed_to}' is not a station here; stations are the facilities in GET /topology")
    unit_type = params.get("unit_type")
    if not isinstance(partner_incident, str) or not partner_incident:
        raise CallRefused(422, "incident_id is required")
    if station is not None and unit_type != station["unit_kind"]:
        return refused_result(events, who, "dispatch_unit", "wrong_station_for_unit_type",
                              {"unit_type": unit_type, "incident_id": partner_incident, "station_id": station["station_id"]})
    ours = links.resolve(partner_incident, params.get("zone_id"), str(unit_type))
    if ours is None:
        return refused_result(events, who, "dispatch_unit", "unknown_incident", {"unit_type": unit_type, "incident_id": partner_incident})
    our_params = {"unit_type": unit_type, "incident_id": ours, **({"station_id": station["station_id"]} if station else {})}
    result = run(actuation, ActuatorCall(actuator_id=our_centre, params=our_params, **common))
    if result.get("unit_id") and result.get("status") in ("dispatched", "duplicate"):
        links.unit_sent(result["unit_id"], partner_incident)
    return {**result, "incident_id": partner_incident, "twin_incident_id": ours}
