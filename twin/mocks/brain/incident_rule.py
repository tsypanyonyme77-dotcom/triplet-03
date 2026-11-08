"""MOCK City Brain for incidents (a stand-in, not the real City Brain). Pure Python, no web
framework: the Brain service (app.py) and the scenario runner (scenarios/incident_chain.py)
both use it.

IncidentBoard   what the Brain knows about incidents, built only from Guardian-verified
                readings (emergency_call, cctv_anomaly collision, building_fire smoke), each carrying the Twin's
                incident_id: type, location, sources, number of calls, confidence, the first
                trusted verdict (trust_ref), and a status from the actuator answers and the
                Twin's unit feedback: reported -> unit_dispatched -> on_scene -> resolved.
                Nothing is dispatched by the board: it lists incidents and waits.
build_call      the actuator call for an operator action on an incident (dispatch_ambulance,
                dispatch_police, dispatch_fire, close_road, open_road, start_pump, stop_pump): requesting_layer
                city_brain, a justification, the trust_ref, an idempotency_key.
IncidentDispatchRule
                AUTO MODE ONLY (a flag, for tests and unattended demos): answers the first
                trusted report of an incident after a short decision delay with an ambulance
                and a police car, or with just a fire truck when the incident is a fire (nobody is
                hurt by a burning building as such); a flood gets a fire truck to rescue the driver,
                a police car and the drainage pump. Manual mode is the default.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from typing import Any

CONTRACT_VERSION = "2026-09-17"
DISPATCH_ACTUATOR_ID = "dispatch-centre-01"
BARRIER_ACTUATOR_ID = "road-barriers-01"
PUMP_ACTUATOR_ID = "drainage-pumps-01"
DECISION_DELAY_S = 3.0
ACTIONS = {
    "dispatch_ambulance": ("dispatch_unit", DISPATCH_ACTUATOR_ID, {"unit_type": "ambulance"}),
    "dispatch_police": ("dispatch_unit", DISPATCH_ACTUATOR_ID, {"unit_type": "police"}),
    "dispatch_fire": ("dispatch_unit", DISPATCH_ACTUATOR_ID, {"unit_type": "fire"}),
    "close_road": ("set_barrier_state", BARRIER_ACTUATOR_ID, {"state": "closed"}),
    "open_road": ("set_barrier_state", BARRIER_ACTUATOR_ID, {"state": "open"}),
    "start_pump": ("set_pump_state", PUMP_ACTUATOR_ID, {"state": "on"}),
    "stop_pump": ("set_pump_state", PUMP_ACTUATOR_ID, {"state": "off"}),
}
STATUS_ORDER = ("reported", "unit_dispatched", "on_scene", "resolved")
_keys = itertools.count(1)


def is_report(reading: dict[str, Any]) -> bool:
    value = reading.get("value", {})
    return bool(value.get("incident_id")) and (
        reading.get("type") == "emergency_call"
        or (reading.get("type") == "cctv_anomaly" and value.get("anomaly_type") == "collision")
        or (reading.get("type") == "building_fire" and value.get("smoke_detected") is True))


@dataclass
class IncidentBoard:
    incidents: dict[str, dict[str, Any]] = field(default_factory=dict)

    def observe(self, reading: dict[str, Any], verdict: dict[str, Any], now_s: float) -> dict[str, Any] | None:
        """One reading with its Guardian verdict. Untrusted readings are ignored. Returns the
        incident when this is its first trusted report, else None."""
        if verdict.get("status") != "trusted" or not is_report(reading):
            return None
        v = reading["value"]
        iid = v["incident_id"]
        new = iid not in self.incidents
        inc = self.incidents.setdefault(iid, {
            "incident_id": iid, "zone_id": reading["zone_id"], "first_report_s": now_s, "trust_ref": verdict["verdict_id"],
            "first_sensor": reading["sensor_id"], "first_type": reading["type"], "sources": [], "call_ids": [],
            "anomaly_ids": [], "building_ids": [], "categories": {}, "confidence": 0.0, "status": "reported", "location": None, "actions": []})
        inc["last_report_s"] = now_s
        if reading["type"] == "emergency_call":
            source, conf = "witness_call", v.get("caller_confidence", 0.0)
            if v["call_id"] not in inc["call_ids"]:
                inc["call_ids"].append(v["call_id"])
            inc["categories"][v["category"]] = inc["categories"].get(v["category"], 0) + 1
        elif reading["type"] == "building_fire":
            source, conf = "smoke_sensor", 0.95
            if v["building_id"] not in inc["building_ids"]:
                inc["building_ids"].append(v["building_id"])
            inc["categories"]["fire"] = inc["categories"].get("fire", 0) + 1
        else:
            source, conf = "camera", v.get("confidence", 0.0)
            if v["anomaly_id"] not in inc["anomaly_ids"]:
                inc["anomaly_ids"].append(v["anomaly_id"])
            inc["categories"]["collision"] = inc["categories"].get("collision", 0) + 1
        if source not in inc["sources"]:
            inc["sources"].append(source)
        inc["confidence"] = round(max(inc["confidence"], conf), 2)
        if v.get("location"):
            inc["location"] = v["location"]
        inc["type"] = max(inc["categories"], key=inc["categories"].get)
        inc["calls"] = len(inc["call_ids"])
        return inc if new else None

    def record_action(self, incident_id: str, action: str, call: dict[str, Any], http: int, result: dict[str, Any]) -> None:
        inc = self.incidents.get(incident_id)
        if inc is None:
            return
        inc["actions"].append({"action": action, "idempotency_key": call.get("idempotency_key"), "http": http,
                               "status": result.get("status"), "unit_id": result.get("unit_id"), "reason": result.get("reason")})
        if action.startswith("dispatch_") and result.get("status") in ("dispatched", "duplicate"):
            self._raise(inc, "unit_dispatched")

    def update_from_twin(self, responses: list[dict[str, Any]]) -> None:
        """The Twin's feedback on what its units are doing (GET /responses): phase per incident."""
        for r in responses:
            inc = self.incidents.get(r["incident_id"])
            if inc is None:
                continue
            inc["twin_phase"] = r["phase"]
            if r["phase"] in ("on_scene", "treating", "loading", "firefighting", "rescuing", "waiting_for_water", "towing"):
                self._raise(inc, "on_scene")
            elif r["phase"] in ("transporting", "cleared", "closed"):
                self._raise(inc, "resolved")

    @staticmethod
    def _raise(inc: dict[str, Any], status: str) -> None:
        if STATUS_ORDER.index(status) > STATUS_ORDER.index(inc["status"]):
            inc["status"] = status

    def list(self) -> list[dict[str, Any]]:
        return sorted(self.incidents.values(), key=lambda i: i["first_report_s"])


def build_call(incident: dict[str, Any], action: str, justification: str | None = None) -> dict[str, Any]:
    """The actuator call for an operator action on an incident, as the City Brain sends it."""
    if action not in ACTIONS:
        raise ValueError(f"unknown action {action!r}; one of {sorted(ACTIONS)}")
    name, actuator_id, params = ACTIONS[action]
    params = {**params, "incident_id": incident["incident_id"]}
    if name == "dispatch_unit":
        params["zone_id"] = incident["zone_id"]
    return {"contract_version": CONTRACT_VERSION, "actuator_id": actuator_id, "action": name, "params": params,
            "requesting_layer": "city_brain",
            "justification": justification or f"{action.replace('_', ' ')} for {incident['incident_id']} "
                                              f"({incident.get('type', '?')}, {len(incident.get('call_ids', []))} calls, "
                                              f"sources {'+'.join(incident.get('sources', []))})",
            "trust_ref": incident["trust_ref"], "idempotency_key": f"brain-{incident['incident_id']}-{action}-{next(_keys):05d}"}


@dataclass
class IncidentDispatchRule:
    """AUTO MODE ONLY. Answers each new incident on the board after a decision delay."""
    decision_delay_s: float = DECISION_DELAY_S
    decisions: list[dict[str, Any]] = field(default_factory=list)
    _pending: dict[str, float] = field(default_factory=dict)   # incident id -> when to decide

    def notice(self, incident: dict[str, Any], now_s: float) -> None:
        self._pending.setdefault(incident["incident_id"], now_s + self.decision_delay_s)

    def due(self, board: IncidentBoard, now_s: float) -> list[tuple[str, dict[str, Any]]]:
        """(action, actuator call) pairs whose decision delay is over, oldest incident first."""
        out = []
        for iid, at in list(self._pending.items()):
            if now_s < at:
                continue
            del self._pending[iid]
            inc = board.incidents[iid]
            if inc.get("type") == "flood":  # a car stuck in water: firefighters get the driver out, the pump drains it
                actions = ["dispatch_fire", "dispatch_police", "start_pump"]
            elif inc.get("type") == "fire":
                actions = ["dispatch_fire"]
            else:
                actions = ["dispatch_ambulance", "dispatch_police"]
            self.decisions.append({"incident_id": iid, "decided_s": now_s, "actions": actions})
            out += [(a, build_call(inc, a, f"auto rule: {a.replace('_', ' ')} for {iid} ({inc.get('type')})")) for a in actions]
        return out
