"""Mock Twin: replays a scripted scenario as signed readings and accepts actuator calls.

A stand-in for the Twin layer (the Twin team's city engine, similar to Cities: Skylines). It follows the shared contract so the Brain
can be demonstrated alone; it does not simulate a city.
"""

from __future__ import annotations

import copy
import os
import time
import uuid
from datetime import timedelta
from typing import Any

from pydantic import ValidationError

from brain import clock
from brain.contracts import (
    CONTRACT_VERSION,
    ActuatorCall,
    BroadcastAlertParams,
    DispatchUnitParams,
    RecallUnitParams,
    SetGridConnectionParams,
    SetSignalPhaseParams,
    SetValveStateParams,
    utcnow,
)
from brain.contracts.keyring import Key, KeyRing
from brain.contracts.signing import sign, verify

# What a dispatched unit reports afterwards, per dispatch mode. The pursuit lasts 15 s: long enough
# for an LLM department team (about 11 s on Groq) to place its perimeter before the arrest, and for
# a hall to read each state on the screen. Scenarios can override this with `on_dispatch`.
DEFAULT_ON_DISPATCH = {
    "pursuit": [
        {"after_ms": 500, "state": "en_route"},
        {"after_ms": 1500, "state": "pursuing"},
        {"after_ms": 15000, "state": "apprehended"},
    ],
    "contain": [
        {"after_ms": 500, "state": "en_route"},
        {"after_ms": 1200, "state": "in_position"},
    ],
    "respond": [
        {"after_ms": 500, "state": "en_route"},
        {"after_ms": 1500, "state": "on_scene"},
    ],
}
# A unit that reports one of these has finished its task and is back in its station's count.
FINISHED = ("apprehended", "lost", "returning")
# A fire or ambulance unit has no arrest to end its task: it reports `returning` this long after it sets out.
NON_POLICE_RETURN_AFTER_MS = 20000


class MockTwin:
    def __init__(self, twin_secret: str | None = None, brain_secret: str | None = None, skew_s: float = 30.0) -> None:
        self.skew_s = skew_s  # a signed call stamped further than this from now is refused
        self._nonces: set[str] = set()  # a call number seen once is never accepted again
        self.twin_secret = twin_secret
        self.brain_secret = brain_secret
        self.actuator_log: list[dict[str, Any]] = []
        self._topology: dict[str, Any] = {}
        self._pending: list[dict[str, Any]] = []  # scripted and follow-up events, by `at_ms`
        self._waiting: list[dict[str, Any]] = []
        self._emitted: list[dict[str, Any]] = []
        self._sequence: dict[str, int] = {}
        self._dispatched: dict[str, str] = {}  # dispatch key -> unit id, for units still out
        self._units: dict[str, dict[str, Any]] = {}  # every unit ever dispatched in this run
        self._units_left: dict[str, int] = {}
        self.stream_id = uuid.uuid4().hex  # changes whenever the stream starts again from zero
        self._alerts: set[str] = set()
        self._on_dispatch = DEFAULT_ON_DISPATCH
        self._signing_keys: dict[str, dict[str, str]] = {}
        self._speed = 1.0
        self._started = time.monotonic()
        self._base_time = utcnow()
        self._last_at_ms = 0.0

    def load_scenario(self, scenario: dict[str, Any], speed: float = 1.0) -> dict[str, Any]:
        """`speed` multiplies playback; 0 releases every event at once (timestamps keep their spacing)."""
        self.actuator_log.clear()
        self._emitted.clear()
        self._sequence.clear()
        self._dispatched.clear()
        self._units.clear()
        self._alerts.clear()
        self.stream_id = uuid.uuid4().hex
        self._topology = scenario.get("topology", {})
        self._units_left = {
            f["actuator_id"]: f.get("units", 2) for f in self._topology.get("facilities", []) if "actuator_id" in f
        }
        events = scenario.get("events", [])
        self._pending = sorted((e for e in events if "at_ms" in e), key=lambda e: e["at_ms"])
        # Events scripted relative to an outcome: released `after_ms` after a unit first reports `after_unit_state`.
        self._waiting = [e for e in events if "after_unit_state" in e]
        self._on_dispatch = {**DEFAULT_ON_DISPATCH, **scenario.get("on_dispatch", {})}
        self._signing_keys = scenario.get("signing_keys", {})  # name -> {kid, secret_env}: which key a reading's `sign_with` means
        self._speed = speed
        self._started = time.monotonic()
        self._base_time = utcnow()
        self._last_at_ms = 0.0
        return {"loaded": scenario.get("id"), "events": len(self._pending), "speed": speed}

    def topology(self) -> dict[str, Any]:
        return self._topology

    def _virtual_now_ms(self) -> float:
        if self._speed <= 0:
            return float("inf")
        return (time.monotonic() - self._started) * 1000 * self._speed

    def _pump(self) -> None:
        now = self._virtual_now_ms()
        while self._pending and self._pending[0]["at_ms"] <= now:
            event = self._pending.pop(0)
            self._last_at_ms = max(self._last_at_ms, event["at_ms"])
            if "replay" in event:
                # An attacker re-sends a reading captured earlier: same bytes, same valid signature.
                wanted = event["replay"]
                self._emitted += [
                    copy.deepcopy(e) for e in self._emitted
                    if e["sensor_id"] == wanted["sensor_id"] and e["sequence_no"] == wanted["sequence_no"]
                ][:1]
                continue
            if event["type"] == "unit_status":
                state = event["value"]["state"]
                if state in FINISHED:
                    self._free(event["value"]["unit_id"])
                due = [w for w in self._waiting if w["after_unit_state"] == state]
                self._waiting = [w for w in self._waiting if w["after_unit_state"] != state]
                self._pending += [{**w, "at_ms": event["at_ms"] + w.get("after_ms", 0)} for w in due]
                self._pending.sort(key=lambda e: e["at_ms"])
            sensor_id = event["sensor_id"]
            self._sequence[sensor_id] = self._sequence.get(sensor_id, 0) + 1
            timestamp = self._base_time + timedelta(milliseconds=event["at_ms"])
            envelope = {
                "contract_version": CONTRACT_VERSION,
                "sensor_id": sensor_id,
                "type": event["type"],
                "zone_id": event["zone_id"],
                "timestamp": timestamp.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
                "sequence_no": self._sequence[sensor_id],
                "value": event["value"],
            }
            if "department_code" in event:
                envelope["department_code"] = event["department_code"]
            key = self._signing_keys.get(event.get("sign_with", ""))
            if key:  # a key-rotation scenario: this reading is signed with a named key and says which (`provenance.kid`)
                envelope = KeyRing({"twin": [Key(key["kid"], "HS256", secret=os.environ.get(key["secret_env"], ""))]}).sign("twin", envelope, signed_by="twin")
            elif self.twin_secret:
                envelope = sign(envelope, self.twin_secret, signed_by="twin")
            self._emitted.append(envelope)

    def list_readings(self, cursor: int = 0, limit: int = 200) -> dict[str, Any]:
        self._pump()
        page = self._emitted[cursor : cursor + limit]
        return {
            "readings": page,
            "next_cursor": cursor + len(page),
            "stream_id": self.stream_id,
            "scenario_done": not self._pending and not self._waiting and cursor + len(page) >= len(self._emitted),
        }

    # ------------------------------------------------------------------ actuators

    def _accept(self, call: dict[str, Any], action: str) -> tuple[ActuatorCall | None, str]:
        try:
            envelope = ActuatorCall.model_validate(call)
        except ValidationError as error:
            first = error.errors()[0]
            return None, f"invalid call: {'.'.join(map(str, first['loc']))}: {first['msg']}"
        if envelope.action != action:
            return None, f"this tool handles {action}, not {envelope.action}"
        if envelope.requesting_layer == "city_brain" and not envelope.trust_ref:
            return None, "trust_ref is required for calls from city_brain"
        if self.brain_secret and not verify(call, self.brain_secret):
            return None, "provenance.hmac is missing or does not match the payload"
        if envelope.issued_at is not None and abs((clock.current().now() - envelope.issued_at).total_seconds()) > self.skew_s:
            return None, f"call_expired: issued_at is more than {self.skew_s} s from now"
        if envelope.nonce is not None:
            if envelope.nonce in self._nonces:
                return None, "nonce_reused: this call was already received"
            self._nonces.add(envelope.nonce)
        return envelope, ""

    def dispatch_unit(self, call: dict[str, Any]) -> dict[str, Any]:
        result = self._dispatch(call)
        self.actuator_log.append({"call": call, "result": result})
        return result

    def _dispatch(self, call: dict[str, Any]) -> dict[str, Any]:
        envelope, problem = self._accept(call, "dispatch_unit")
        if envelope is None:
            return {"status": "rejected", "reason": problem}
        try:
            params = DispatchUnitParams.model_validate(envelope.params)
        except ValidationError as error:
            first = error.errors()[0]
            return {"status": "rejected", "reason": f"invalid params: {'.'.join(map(str, first['loc']))}: {first['msg']}"}

        mode = params.mode or "respond"
        subject = params.target_id if mode == "pursuit" and params.target_id else params.zone_id
        key = f"{params.incident_id}|{params.unit_type}|{mode}|{subject}"
        if key in self._dispatched:
            return {"status": "duplicate", "unit_id": self._dispatched[key], "eta_minutes": 0}
        if envelope.actuator_id in self._units_left and self._units_left[envelope.actuator_id] <= 0:
            return {"status": "rejected", "reason": f"no unit available at {envelope.actuator_id}"}
        if envelope.actuator_id in self._units_left:
            self._units_left[envelope.actuator_id] -= 1

        unit_id = f"unit-{params.unit_type[:1]}-{len(self._units) + 1:02d}"
        self._dispatched[key] = unit_id
        self._units[unit_id] = {"key": key, "actuator_id": envelope.actuator_id, "unit_type": params.unit_type,
                                "zone_id": params.zone_id, "incident_id": params.incident_id, "out": True}
        for step in self._on_dispatch.get(mode, []):
            self._report(unit_id, step["state"], step["after_ms"])
        if params.unit_type != "police" and mode == "respond":
            self._report(unit_id, "returning", NON_POLICE_RETURN_AFTER_MS)
        return {"status": "dispatched", "unit_id": unit_id, "eta_minutes": 3}

    def _report(self, unit_id: str, state: str, after_ms: float) -> None:
        unit = self._units[unit_id]
        base = self._last_at_ms if self._speed <= 0 else self._virtual_now_ms()
        self._pending.append({
            "at_ms": base + after_ms,
            "sensor_id": f"unit-feed-{unit['unit_type']}",
            "type": "unit_status",
            "zone_id": unit["zone_id"],
            "value": {"unit_id": unit_id, "incident_id": unit["incident_id"], "state": state},
        })
        self._pending.sort(key=lambda e: e["at_ms"])

    def _free(self, unit_id: str, recalled: bool = False) -> None:
        """The unit is back in its station's count.

        A unit that finished its task keeps its place in the dispatch table, so the same call
        sent again is still answered `duplicate`. A recalled unit gives the place up: the
        Brain may send another unit to that zone.
        """
        unit = self._units.get(unit_id)
        if unit is None or not unit["out"]:
            return
        unit["out"] = False
        if recalled:
            self._dispatched.pop(unit["key"], None)
        if unit["actuator_id"] in self._units_left:
            self._units_left[unit["actuator_id"]] += 1

    def recall_unit(self, call: dict[str, Any]) -> dict[str, Any]:
        result = self._recall(call)
        self.actuator_log.append({"call": call, "result": result})
        return result

    def _recall(self, call: dict[str, Any]) -> dict[str, Any]:
        envelope, problem = self._accept(call, "recall_unit")
        if envelope is None:
            return {"status": "rejected", "reason": problem}
        try:
            params = RecallUnitParams.model_validate(envelope.params)
        except ValidationError as error:
            first = error.errors()[0]
            return {"status": "rejected", "reason": f"invalid params: {'.'.join(map(str, first['loc']))}: {first['msg']}"}
        unit = self._units.get(params.unit_id)
        if unit is None or unit["incident_id"] != params.incident_id:
            return {"status": "rejected", "reason": f"no unit {params.unit_id} is out for {params.incident_id}"}
        if not unit["out"]:
            return {"status": "duplicate", "unit_id": params.unit_id}
        # Whatever the unit had still to report on its old task will not happen now.
        self._pending = [
            e for e in self._pending if not (e.get("type") == "unit_status" and e["value"]["unit_id"] == params.unit_id)
        ]
        self._free(params.unit_id, recalled=True)
        self._report(params.unit_id, "returning", 300)
        return {"status": "recalled", "unit_id": params.unit_id}

    def broadcast_alert(self, call: dict[str, Any]) -> dict[str, Any]:
        result = self._alert(call)
        self.actuator_log.append({"call": call, "result": result})
        return result

    def _params(self, call: dict[str, Any], action: str, model: type[Any]) -> tuple[Any | None, str]:
        """The call's validated params, or the reason the Twin refuses it."""
        envelope, problem = self._accept(call, action)
        if envelope is None:
            return None, problem
        try:
            return model.model_validate(envelope.params), ""
        except ValidationError as error:
            first = error.errors()[0]
            return None, f"invalid params: {'.'.join(map(str, first['loc']))}: {first['msg']}"

    def _alert(self, call: dict[str, Any]) -> dict[str, Any]:
        params, problem = self._params(call, "broadcast_alert", BroadcastAlertParams)
        if params is None:
            return {"status": "rejected", "reason": problem}
        key = f"{params.zone_id}|{params.channel}|{params.message}"
        if key in self._alerts:
            return {"status": "duplicate"}
        self._alerts.add(key)
        return {"status": "broadcast", "zone_id": params.zone_id, "channel": params.channel}

    def _logged(self, call: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        self.actuator_log.append({"call": call, "result": result})
        return result

    def set_signal_phase(self, call: dict[str, Any]) -> dict[str, Any]:
        params, problem = self._params(call, "set_signal_phase", SetSignalPhaseParams)
        if params is None:
            return self._logged(call, {"status": "rejected", "reason": problem})
        reverts_at = utcnow() + timedelta(seconds=params.duration_s)
        return self._logged(call, {"status": "set", "current_phase": params.phase,
                                   "reverts_at": reverts_at.isoformat(timespec="milliseconds").replace("+00:00", "Z")})

    def set_valve_state(self, call: dict[str, Any]) -> dict[str, Any]:
        params, problem = self._params(call, "set_valve_state", SetValveStateParams)
        if params is None:
            return self._logged(call, {"status": "rejected", "reason": problem})
        return self._logged(call, {"status": "set", "current_state": params.state})

    def set_grid_connection(self, call: dict[str, Any]) -> dict[str, Any]:
        params, problem = self._params(call, "set_grid_connection", SetGridConnectionParams)
        if params is None:
            return self._logged(call, {"status": "rejected", "reason": problem})
        return self._logged(call, {"status": "set", "affected_load_kw": 0.0})
