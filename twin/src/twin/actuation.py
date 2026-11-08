"""Actuator calls, whichever door they come through (our POST /actuators/call, the City Brain's
POST /actuators/{action} and MCP tools, the Guardian's POST /tools/{action}).

A door authenticates the caller and turns its message into our ActuatorCall; this module does the rest,
the same way for everyone: contract version, action, actuator id, who may call it, trust_ref,
idempotency, the actuator itself, and the events on the timeline.
"""
from __future__ import annotations

from typing import Any

from twin.actuators import ACTUATORS, ParamError
from twin.city.base import CitySource
from twin.contract import CONTRACT_VERSION, ActuatorCall, now_iso
from twin.devices import DeviceRegistry
from twin.events import EventLog

# the event each result status puts on the timeline
EVENT_KIND = {"dispatched": "unit_dispatched", "closed": "road_closed", "opened": "road_opened", "quarantined": "device_quarantined",
              "isolated": "device_isolated", "cleared": "device_cleared", "on": "pump_started", "off": "pump_stopped",
              "broadcast": "alert_broadcast", "recalled": "unit_recalled", "duplicate": "actuator_duplicate"}


class CallRefused(Exception):
    """The call is refused before any actuator runs. `status_code` is the HTTP status a door answers with."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


class Actuation:
    def __init__(self, city: CitySource, devices: DeviceRegistry, events: EventLog) -> None:
        self.city, self.devices, self.events = city, devices, events
        self.answered: dict[str, dict[str, Any]] = {}   # idempotency_key -> the first call and its response

    def new_run(self) -> None:
        """Idempotency keys of the old run no longer apply."""
        self.answered.clear()

    def refuse(self, status_code: int, detail: str, reason: str, message: str) -> CallRefused:
        self.events.emit("actuator_rejected", message, reason=reason)
        return CallRefused(status_code, detail)

    def execute(self, call: ActuatorCall) -> dict[str, Any]:
        """Runs an authenticated call and returns our response envelope (`result` holds the actuator's answer).
        Raises CallRefused for a call that must not run."""
        if call.contract_version != CONTRACT_VERSION:
            raise CallRefused(400, f"unsupported contract_version '{call.contract_version}', this twin speaks '{CONTRACT_VERSION}'")
        spec = ACTUATORS.get(call.action)
        if spec is None:
            raise CallRefused(400, f"unknown action '{call.action}', known actions: {sorted(ACTUATORS)}")
        if call.actuator_id != spec["actuator_id"]:
            raise CallRefused(400, f"action '{call.action}' belongs to actuator_id '{spec['actuator_id']}', got '{call.actuator_id}'")
        if spec.get("guardian_only") and call.requesting_layer != "guardian":
            raise self.refuse(403, f"{call.action} may only be requested by the guardian", "guardian_only",
                              f"{call.action} rejected: guardian only")
        if call.requesting_layer == "city_brain" and not call.trust_ref:
            raise self.refuse(403, "trust_ref is required for city_brain calls: act only on a Guardian-verified reading",
                              "trust_ref_required", f"{call.action} rejected: city_brain call without trust_ref")
        if call.idempotency_key and call.idempotency_key in self.answered:
            first = self.answered[call.idempotency_key]
            if (first["action"], first["params"]) != (call.action, call.params):
                raise CallRefused(409, f"idempotency_key '{call.idempotency_key}' was used for a different call")
            self.events.emit("actuator_call_replayed", f"{call.action} retried with key {call.idempotency_key}: first answer returned",
                             action=call.action, idempotency_key=call.idempotency_key)
            return {**first["response"], "replayed": True}
        self.events.emit("actuator_call_received", f"{call.requesting_layer} called {call.action}: {call.justification}",
                         action=call.action, params=call.params, requesting_layer=call.requesting_layer, trust_ref=call.trust_ref,
                         idempotency_key=call.idempotency_key)
        try:
            result = spec["handler"](call.params, self.city, self.devices)
        except ParamError as exc:
            raise CallRefused(422, str(exc)) from exc
        kind = EVENT_KIND.get(result["status"], "actuator_rejected")
        self.events.emit(kind, f"{call.action} -> {result['status']} "
                               f"({result.get('unit_id') or result.get('pump_id') or result.get('alert_id') or result.get('reason', '')})",
                         action=call.action, result=result)
        response = {"contract_version": CONTRACT_VERSION, "actuator_id": call.actuator_id, "action": call.action,
                    "received_at": now_iso(), "result": result}
        if call.idempotency_key:
            response["idempotency_key"] = call.idempotency_key
            self.answered[call.idempotency_key] = {"action": call.action, "params": call.params, "response": response}
        return response
