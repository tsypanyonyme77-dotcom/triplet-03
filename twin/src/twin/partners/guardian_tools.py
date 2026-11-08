"""The calls the Guardian sends the Twin (guardian/INTERFACE.md section 4.3): POST /tools/{action} with its
actuator call `{call_id, actuator_id, action, params, zone_id, requesting_layer, trust_ref, justification,
incident_id}`. Two kinds arrive:
  - the City Brain's calls the Guardian audited and forwards (`requesting_layer: "brain"`); a dispatch names
    the station in `params.station_id` and the City Brain's incident in `incident_id`,
  - the Guardian's own containment: quarantine_device, isolate_sensor, clear_quarantine (`device_id` only;
    the reason is the call's justification).
The answer is always the Guardian's reply shape `{status: ok | rejected, current_state, reverts_at, ...}`,
with HTTP 200 even for a refusal, since the Guardian counts any HTTP error as `twin_unreachable`.

Authentication: the Guardian sends no key today. When TWIN_TOOLS_API_KEY is set, `X-API-Key` must match it.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Header, HTTPException

from twin.actuation import Actuation, CallRefused
from twin.actuators import ACTUATORS, DEVICE_ACTUATOR_ID
from twin.city.base import CitySource
from twin.contract import CONTRACT_VERSION, ActuatorCall
from twin.events import EventLog
from twin.partners import partner_dispatch
from twin.partners.incident_links import IncidentLinks

CONTAINMENT = ("quarantine_device", "isolate_sensor", "clear_quarantine")
OK_STATUSES = {"dispatched", "duplicate", "quarantined", "isolated", "cleared", "closed", "opened", "on", "off", "broadcast", "recalled"}


def _device_id(raw: dict[str, Any]) -> str:
    """The Guardian names the sensors it was sent; a flow meter is the water level gauge of the same street."""
    device = str((raw.get("params") or {}).get("device_id") or raw.get("actuator_id") or "")
    return "wl-" + device.removeprefix("flow-") if device.startswith("flow-") else device


class GuardianDoor:
    def __init__(self, actuation: Actuation, city: CitySource, links: IncidentLinks, events: EventLog, api_key: str = "") -> None:
        self.actuation, self.city, self.links, self.events, self.api_key = actuation, city, links, events, api_key

    def handle(self, action: str, raw: Any) -> dict[str, Any]:
        """Returns the actuator's result, flat; raises CallRefused for a call that cannot run."""
        if not isinstance(raw, dict):
            raise CallRefused(422, "the call must be a JSON object")
        if raw.get("action", action) != action:
            raise CallRefused(400, f"the call's action '{raw.get('action')}' does not match the path '{action}'")
        layer = raw.get("requesting_layer")
        common = {"contract_version": CONTRACT_VERSION, "action": action,
                  "justification": str(raw.get("justification") or f"forwarded by the guardian ({raw.get('call_id')})")[:500],
                  "trust_ref": raw.get("trust_ref"),
                  "idempotency_key": f"guardian-call:{raw['call_id']}"[:128] if raw.get("call_id") else None}
        if action in CONTAINMENT:
            if layer != "guardian":
                raise CallRefused(403, f"{action} is the Guardian's own containment: requesting_layer must be 'guardian'")
            params = {"device_id": _device_id(raw)}
            if action != "clear_quarantine":
                params["reason"] = common["justification"]
            return partner_dispatch.run(self.actuation, ActuatorCall(actuator_id=DEVICE_ACTUATOR_ID, params=params,
                                                                     requesting_layer="guardian", **common))
        if layer not in ("brain", "city_brain"):
            raise CallRefused(403, f"{action} is forwarded for the City Brain: requesting_layer must be 'brain'")
        common["requesting_layer"] = "city_brain"
        params = raw.get("params") or {}
        if action == "dispatch_unit":
            station = params.get("station_id") or raw.get("actuator_id")
            return partner_dispatch.dispatch(self.actuation, self.city, self.links, self.events, who="guardian",
                                             addressed_to=station if str(station).startswith("dispatch-") else None,
                                             params={**params, "zone_id": raw.get("zone_id")},
                                             partner_incident=raw.get("incident_id") or params.get("incident_id"), common=common)
        if action not in ACTUATORS or action in ("broadcast_alert",):
            return partner_dispatch.refused_result(self.events, "guardian", action, "not_supported", {"action": action})
        return partner_dispatch.run(self.actuation, ActuatorCall(actuator_id=ACTUATORS[action]["actuator_id"], params=params, **common))

    @staticmethod
    def reply(result: dict[str, Any]) -> dict[str, Any]:
        """The Guardian's reply shape. `duplicate` is a success: what was asked is already so."""
        ok = result.get("status") in OK_STATUSES
        out: dict[str, Any] = {"status": "ok" if ok else "rejected", "current_state": result, "reverts_at": None}
        if result.get("unit_id"):
            out["unit_id"] = result["unit_id"]
        if result.get("eta_minutes") is not None:
            out["eta_s"] = round(result["eta_minutes"] * 60, 1)
        if not ok:
            out["reason"] = result.get("reason", "rejected")
        return out


def guardian_router(door: GuardianDoor) -> APIRouter:
    router = APIRouter(tags=["guardian"])

    @router.post("/tools/{action}")
    async def tool(action: str, call: Any = Body(...), x_api_key: str | None = Header(default=None)):
        # async on purpose: runs on the event loop, never in the middle of a tick that changes the city
        if door.api_key and x_api_key != door.api_key:
            door.events.emit("actuator_rejected", "guardian tool call rejected: bad or missing X-API-Key", reason="unauthorized")
            raise HTTPException(401, "missing or invalid X-API-Key header")
        try:
            return door.reply(door.handle(action, call))
        except CallRefused as exc:
            return door.reply({"status": "rejected", "reason": f"http_{exc.status_code}: {exc.detail}"})

    return router
