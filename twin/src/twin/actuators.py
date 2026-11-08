"""Actuator registry. Each actuator validates its params and returns a result dict (never raises on business errors)."""
from __future__ import annotations

from typing import Any, Callable

from twin.city.base import CitySource
from twin.devices import DeviceRegistry

DISPATCH_ACTUATOR_ID = "dispatch-centre-01"
BARRIER_ACTUATOR_ID = "road-barriers-01"
DEVICE_ACTUATOR_ID = "device-control-01"
PUMP_ACTUATOR_ID = "drainage-pumps-01"
ALERT_ACTUATOR_ID = "public-alerts-01"
UNIT_TYPES = ("police", "ambulance", "fire")
ALERT_CHANNELS = ("sms", "siren", "app")
ROAD_STATES = ("closed", "open")
PUMP_STATES = ("on", "off")


class ParamError(ValueError):
    """Raised for malformed params; the API turns it into HTTP 422 with a clear message."""


def _dispatch_unit(params: dict[str, Any], city: CitySource, _devices: DeviceRegistry) -> dict[str, Any]:
    unit_type, incident_id = params.get("unit_type"), params.get("incident_id")
    if unit_type not in UNIT_TYPES:
        raise ParamError(f"params.unit_type must be one of {list(UNIT_TYPES)}")
    if not isinstance(incident_id, str) or not incident_id:
        raise ParamError("params.incident_id is required: the incident_id of an emergency_call or cctv_anomaly reading")
    station_id = params.get("station_id")
    if station_id is not None and (not isinstance(station_id, str) or not station_id):
        raise ParamError("params.station_id must be a non-empty string, a station from the topology")
    result = city.dispatch_unit(unit_type, incident_id, station_id)
    eta = result.pop("eta_seconds", None)
    if eta is not None:
        result["eta_minutes"] = round(eta / 60.0, 2)
    return {**result, "unit_type": unit_type, "incident_id": incident_id}


def _set_barrier_state(params: dict[str, Any], city: CitySource, _devices: DeviceRegistry) -> dict[str, Any]:
    state, road_id, incident_id = params.get("state"), params.get("road_id"), params.get("incident_id")
    if state not in ROAD_STATES:
        raise ParamError(f"params.state must be one of {list(ROAD_STATES)}")
    if (road_id is None) == (incident_id is None):
        raise ParamError("give exactly one of params.road_id (e.g. '1-2') or params.incident_id")
    for name, value in (("road_id", road_id), ("incident_id", incident_id)):
        if value is not None and (not isinstance(value, str) or not value):
            raise ParamError(f"params.{name} must be a non-empty string")
    return city.set_barrier_state(state, road_id=road_id, incident_id=incident_id)


def _set_pump_state(params: dict[str, Any], city: CitySource, _devices: DeviceRegistry) -> dict[str, Any]:
    state, pump_id, incident_id = params.get("state"), params.get("pump_id"), params.get("incident_id")
    if state not in PUMP_STATES:
        raise ParamError(f"params.state must be one of {list(PUMP_STATES)}")
    if (pump_id is None) == (incident_id is None):
        raise ParamError("give exactly one of params.pump_id (e.g. 'pump-2-3') or params.incident_id")
    for name, value in (("pump_id", pump_id), ("incident_id", incident_id)):
        if value is not None and (not isinstance(value, str) or not value):
            raise ParamError(f"params.{name} must be a non-empty string")
    return city.set_pump_state(state, pump_id=pump_id, incident_id=incident_id)


def _broadcast_alert(params: dict[str, Any], city: CitySource, _devices: DeviceRegistry) -> dict[str, Any]:
    zone_id, channel, message = params.get("zone_id"), params.get("channel"), params.get("message")
    if not isinstance(zone_id, str) or not zone_id:
        raise ParamError("params.zone_id is required: the zone to alert")
    if channel not in ALERT_CHANNELS:
        raise ParamError(f"params.channel must be one of {list(ALERT_CHANNELS)}")
    if not isinstance(message, str) or not 1 <= len(message) <= 280:
        raise ParamError("params.message must be a string of 1 to 280 characters")
    return city.broadcast_alert(zone_id, channel, message)


def _device_id(params: dict[str, Any], city: CitySource) -> tuple[str, bool]:
    device_id = params.get("device_id")
    if not isinstance(device_id, str) or not device_id:
        raise ParamError("params.device_id is required: a sensor_id from GET /sensors, e.g. cam-n2")
    return device_id, device_id in city.device_ids()


def _block(mode: str, done: str) -> Callable[[dict[str, Any], CitySource, DeviceRegistry], dict[str, Any]]:
    def handler(params: dict[str, Any], city: CitySource, devices: DeviceRegistry) -> dict[str, Any]:
        device_id, known = _device_id(params, city)
        if not known:
            return {"status": "rejected", "device_id": device_id, "reason": "unknown_device"}
        reason = params.get("reason")
        if not isinstance(reason, str) or not reason:
            raise ParamError("params.reason is required: why the device is cut off")
        changed = devices.block(device_id, mode, reason)
        return {"status": done if changed else "duplicate", "device_id": device_id, "quarantined_until": None}
    return handler


def _clear_quarantine(params: dict[str, Any], city: CitySource, devices: DeviceRegistry) -> dict[str, Any]:
    device_id, _ = _device_id(params, city)
    return {"status": "cleared" if devices.clear(device_id) else "duplicate", "device_id": device_id}


# action name -> handler, expected actuator_id, description, params and result in words and as JSON Schema
ACTUATORS: dict[str, dict[str, Any]] = {}

ACTUATORS["dispatch_unit"] = {
    "handler": _dispatch_unit,
    "actuator_id": DISPATCH_ACTUATOR_ID,
    "department": "emergency",
    "description": "Send a police car, ambulance or fire truck from its station to an incident. Idempotent per incident and "
                   "unit type: a second call returns 'duplicate' with the unit already sent. Draft dictionary action.",
    "params": {"unit_type": "police | ambulance | fire", "incident_id": "string, from an emergency_call or cctv_anomaly reading",
               "zone_id": "string, optional (the incident's zone)",
               "station_id": "string, optional: only a unit of this station may go (stations are in GET /topology)"},
    "result": {"status": "dispatched | duplicate | rejected", "unit_id": "string", "eta_minutes": "number",
               "reason": "string, only when rejected (unknown_incident, no_unit_available, unknown_unit_type, unknown_station)"},
    "params_schema": {
        "type": "object", "required": ["unit_type", "incident_id"], "additionalProperties": False,
        "properties": {"unit_type": {"enum": list(UNIT_TYPES)}, "incident_id": {"type": "string", "minLength": 1},
                       "zone_id": {"type": "string"}, "station_id": {"type": "string", "minLength": 1}}},
    "result_schema": {
        "type": "object", "required": ["status"],
        "properties": {"status": {"enum": ["dispatched", "duplicate", "rejected"]}, "unit_id": {"type": "string"},
                       "eta_minutes": {"type": "number"}, "unit_type": {"enum": list(UNIT_TYPES)},
                       "incident_id": {"type": "string"},
                       "reason": {"enum": ["unknown_incident", "no_unit_available", "unknown_unit_type", "unknown_station"]}}},
}

ACTUATORS["broadcast_alert"] = {
    "handler": _broadcast_alert,
    "actuator_id": ALERT_ACTUATOR_ID,
    "department": "civil_protection",
    "description": "Send a public alert to everyone in a zone (sms, siren or app). Recorded on the timeline; the simulated "
                   "people do not react to it yet. Extended dictionary action.",
    "params": {"zone_id": "string, a zone from GET /zones", "channel": "sms | siren | app", "message": "string, 1 to 280 characters"},
    "result": {"status": "broadcast | rejected", "alert_id": "string", "zone_id": "string", "channel": "string",
               "reason": "string, only when rejected (unknown_zone)"},
    "params_schema": {
        "type": "object", "required": ["zone_id", "channel", "message"], "additionalProperties": False,
        "properties": {"zone_id": {"type": "string", "minLength": 1}, "channel": {"enum": list(ALERT_CHANNELS)},
                       "message": {"type": "string", "minLength": 1, "maxLength": 280}}},
    "result_schema": {
        "type": "object", "required": ["status"],
        "properties": {"status": {"enum": ["broadcast", "rejected"]}, "alert_id": {"type": "string"}, "zone_id": {"type": "string"},
                       "channel": {"enum": list(ALERT_CHANNELS)}, "reason": {"enum": ["unknown_zone", "unknown_channel"]}}},
}

ACTUATORS["set_barrier_state"] = {
    "handler": _set_barrier_state,
    "actuator_id": BARRIER_ACTUATOR_ID,
    "department": "police",
    "description": "Close a street to traffic (barriers at both ends, both directions) or reopen it. Cars that can are re-routed "
                   "round it; the others stop before it; emergency units ignore it. Give the street (road_id) or the incident "
                   "whose wrecks block it. Idempotent: closing a closed street returns 'duplicate'. The draft dictionary has "
                   "set_barrier_state(barrier_id, open|closed); a street id instead of a barrier id is proposed.",
    "params": {"state": "closed | open", "road_id": "string '<node>-<node>', e.g. '1-2' (or incident_id)",
               "incident_id": "string, the incident whose street to close (or road_id)"},
    "result": {"status": "closed | opened | duplicate | rejected", "barrier_ids": "list of 'barrier-<node>-<node>'",
               "state": "closed | open", "edges": "directed edges changed", "reason": "string, only when rejected"},
    "params_schema": {
        "type": "object", "required": ["state"], "additionalProperties": False,
        "oneOf": [{"required": ["road_id"]}, {"required": ["incident_id"]}],
        "properties": {"state": {"enum": list(ROAD_STATES)}, "road_id": {"type": "string", "pattern": "^[0-9]+-[0-9]+$"},
                       "incident_id": {"type": "string", "minLength": 1}}},
    "result_schema": {
        "type": "object", "required": ["status"],
        "properties": {"status": {"enum": ["closed", "opened", "duplicate", "rejected"]},
                       "barrier_ids": {"type": "array", "items": {"type": "string"}}, "state": {"enum": list(ROAD_STATES)},
                       "edges": {"type": "array"},
                       "reason": {"enum": ["unknown_road", "unknown_incident", "no_open_accident_at_incident", "unknown_state",
                                           "road_id_or_incident_id_required"]}}},
}

ACTUATORS["set_pump_state"] = {
    "handler": _set_pump_state,
    "actuator_id": PUMP_ACTUATOR_ID,
    "department": "water",
    "description": "Start or stop the drainage pump of a flood-prone low point. Running, it adds its capacity to the storm "
                   "drain's, so the water goes down faster (water_level readings show it). Give the pump (pump_id) or the "
                   "incident at the flooded street. Idempotent: starting a running pump returns 'duplicate'. The draft "
                   "dictionary has set_pump_state(pump_id, on|off, flow_target); incident_id is proposed, flow_target is not "
                   "supported (the pump runs at full capacity).",
    "params": {"state": "on | off", "pump_id": "string, e.g. 'pump-2-3' (or incident_id)",
               "incident_id": "string, an incident at a flooded street (or pump_id)"},
    "result": {"status": "on | off | duplicate | rejected", "pump_id": "string", "state": "on | off",
               "capacity_m3s": "number, what the pump adds while on", "reason": "string, only when rejected"},
    "params_schema": {
        "type": "object", "required": ["state"], "additionalProperties": False,
        "oneOf": [{"required": ["pump_id"]}, {"required": ["incident_id"]}],
        "properties": {"state": {"enum": list(PUMP_STATES)}, "pump_id": {"type": "string", "minLength": 1},
                       "incident_id": {"type": "string", "minLength": 1}}},
    "result_schema": {
        "type": "object", "required": ["status"],
        "properties": {"status": {"enum": ["on", "off", "duplicate", "rejected"]}, "pump_id": {"type": "string"},
                       "state": {"enum": list(PUMP_STATES)}, "capacity_m3s": {"type": "number"},
                       "reason": {"enum": ["unknown_pump", "unknown_incident", "no_pump_at_incident", "unknown_state",
                                           "pump_id_or_incident_id_required"]}}},
}

_DEVICE_PARAMS = {"device_id": "string, a sensor_id from GET /sensors", "reason": "string, why the device is cut off"}
_BLOCK_SCHEMA = {"type": "object", "required": ["device_id", "reason"], "additionalProperties": False,
                 "properties": {"device_id": {"type": "string", "minLength": 1}, "reason": {"type": "string", "minLength": 1}}}


def _block_result_schema(done: str) -> dict[str, Any]:
    return {"type": "object", "required": ["status", "device_id"],
            "properties": {"status": {"enum": [done, "duplicate", "rejected"]}, "device_id": {"type": "string"},
                           "quarantined_until": {"type": ["string", "null"]}, "reason": {"enum": ["unknown_device"]}}}


ACTUATORS["quarantine_device"] = {
    "handler": _block("quarantine", "quarantined"),
    "actuator_id": DEVICE_ACTUATOR_ID,
    "department": "security",
    "guardian_only": True,
    "description": "Cut a device off: its readings, and those of the sensors named after it, stop reaching the other layers. "
                   "The Twin keeps simulating it. Lasts until clear_quarantine or a new run. Idempotent. Guardian only.",
    "params": _DEVICE_PARAMS,
    "result": {"status": "quarantined | duplicate | rejected", "device_id": "string", "quarantined_until": "null, no expiry"},
    "params_schema": _BLOCK_SCHEMA,
    "result_schema": _block_result_schema("quarantined"),
}

ACTUATORS["isolate_sensor"] = {
    "handler": _block("isolate", "isolated"),
    "actuator_id": DEVICE_ACTUATOR_ID,
    "department": "security",
    "guardian_only": True,
    "description": "The same effect as quarantine_device, recorded as isolating one sensor. Idempotent. Guardian only.",
    "params": _DEVICE_PARAMS,
    "result": {"status": "isolated | duplicate | rejected", "device_id": "string", "quarantined_until": "null, no expiry"},
    "params_schema": _BLOCK_SCHEMA,
    "result_schema": _block_result_schema("isolated"),
}

ACTUATORS["clear_quarantine"] = {
    "handler": _clear_quarantine,
    "actuator_id": DEVICE_ACTUATOR_ID,
    "department": "security",
    "guardian_only": True,
    "description": "Let a device send readings again. Clearing a device that is not cut off returns 'duplicate'. Guardian only.",
    "params": {"device_id": "string, a sensor_id from GET /sensors"},
    "result": {"status": "cleared | duplicate", "device_id": "string"},
    "params_schema": {"type": "object", "required": ["device_id"], "additionalProperties": False,
                      "properties": {"device_id": {"type": "string", "minLength": 1}}},
    "result_schema": {"type": "object", "required": ["status", "device_id"],
                      "properties": {"status": {"enum": ["cleared", "duplicate"]}, "device_id": {"type": "string"}}},
}


def describe() -> list[dict[str, Any]]:
    """The actuator catalog (GET /actuators): action, actuator_id, department, description, params and result."""
    return [{"action": name, **{k: v for k, v in spec.items() if k != "handler"}} for name, spec in ACTUATORS.items()]
