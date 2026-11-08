"""Twin simulator: correlated physics (rain → flow → level ~10 min later, diurnal traffic and load),
actuator effects, signed envelopes with sequence numbers, and the fault/attack injector."""

from __future__ import annotations

import math
import random
import secrets
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from guardian.clock import Clock, iso
from mocks.common.signing import sign_envelope
from mocks.twin_mock.city import ACTUATORS, BASE_FLOW, BASE_LEVEL, CAPACITY_KW, SENSORS, TZ_OFFSET_H, ZONES

INJECTIONS = [
    "fake_flood", "spike", "stuck", "replay", "bad_hmac", "call_flood", "duplicate_call", "silence",
    "fire_in_sea", "coordinated", "valve_stuck", "slow_drift", "real_flood", "sequence_reset", "call", "clear",
]


@dataclass
class MockSensor:
    sensor_id: str
    sensor_type: str
    zone_id: str
    interval: float | None
    seq: int = 0
    next_due: datetime | None = None
    reset_pending: bool = True  # agreed restart rule: first reading after (re)start carries sequence_reset
    last_envelopes: deque[dict[str, Any]] = field(default_factory=lambda: deque(maxlen=5))


@dataclass
class Override:
    kind: str  # fixed | stuck | drift | spike
    values: dict[str, Any] = field(default_factory=dict)
    step: float = 0.0
    field_: str | None = None
    applied: int = 0
    interval: float | None = None


class Simulator:
    def __init__(self, clock: Clock, hmac_key: str, seed: int = 7, speed: float = 1.0) -> None:
        self.clock, self.key, self.speed = clock, hmac_key, speed
        self.rng = random.Random(seed)
        self.sensors = {sid: MockSensor(sid, t, z, iv) for sid, (t, z, iv) in SENSORS.items()}
        self.rain = {z: 0.0 for z in ZONES}
        self.rain_target = {z: 0.0 for z in ZONES}
        self.inflow = dict(BASE_FLOW)
        self.flow = dict(BASE_FLOW)
        self.level = dict(BASE_LEVEL)
        self.valve_closed = {z: False for z in ZONES}
        self.grid_connected = {z: True for z in ZONES}
        self.green_until: dict[str, datetime] = {}
        self.stuck_actuators: set[str] = set()
        self.overrides: dict[str, Override] = {}
        self.bad_hmac: dict[str, int] = {}
        self.silenced: set[str] = set()
        self.silence_all = False
        self.isolated: set[str] = set()
        self.quarantined: set[str] = set()
        self.queue: list[dict[str, Any]] = []
        self.tool_log: list[dict[str, Any]] = []
        self.buffer: deque[dict[str, Any]] = deque(maxlen=20_000)
        self.buffer_offset = 0
        self.last_call: dict[str, Any] | None = None
        self._last_step: datetime | None = None

    # ---------- physics
    def local_hour(self, now: datetime) -> float:
        t = now + timedelta(hours=TZ_OFFSET_H)
        return t.hour + t.minute / 60

    def congestion(self, now: datetime) -> float:
        h = self.local_hour(now)
        return min(1.0, 0.12 + 0.6 * math.exp(-(((h - 8) / 1.2) ** 2)) + 0.55 * math.exp(-(((h - 17.5) / 1.3) ** 2)))

    def advance_physics(self, now: datetime) -> None:
        dt = 0.0 if self._last_step is None else (now - self._last_step).total_seconds() * self.speed
        self._last_step = now
        if dt <= 0:
            return

        def approach(cur: float, target: float, tau: float) -> float:
            return target + (cur - target) * math.exp(-dt / tau)

        for z in ZONES:
            self.rain[z] = approach(self.rain[z], self.rain_target[z], 60)
        for z in BASE_FLOW:
            self.inflow[z] = approach(self.inflow[z], BASE_FLOW[z] + 0.07 * self.rain[z], 120)
            valve = next((a for a, (t, zz) in ACTUATORS.items() if t == "valve" and zz == z), None)
            closed = self.valve_closed[z] and valve not in self.stuck_actuators
            self.flow[z] = approach(self.flow[z], self.inflow[z] * (0.08 if closed else 1.0), 3 if closed else 20)
            self.level[z] = approach(self.level[z], BASE_LEVEL[z] + 0.5 * max(0.0, self.inflow[z] - BASE_FLOW[z]), 300)

    def true_value(self, s: MockSensor, now: datetime) -> dict[str, Any]:
        g, z = self.rng.gauss, s.zone_id
        if s.sensor_type == "water_level":
            return {"level_m": round(max(0.0, self.level[z] + g(0, 0.004)), 4)}
        if s.sensor_type == "flow_meter":
            return {"flow_rate_m3s": round(max(0.0, self.flow[z] + g(0, 0.015)), 4)}
        if s.sensor_type == "rain_gauge":
            r = self.rain[z]
            return {"rainfall_mm_h": round(max(0.0, r + (g(0, 0.4) if r > 0.5 else 0.0)), 3)}
        if s.sensor_type == "air_quality":
            return {"aqi": round(max(0.0, 42 + g(0, 2.5)), 1), "smoke": False}
        if s.sensor_type == "traffic_camera":
            c = self.congestion(now)
            green = self.green_until.get(z)
            boost = 1.25 if green and now < green and "sig-port-01" not in self.stuck_actuators else 1.0
            c = max(0.0, min(1.0, c + g(0, 0.01)))
            return {"vehicle_count": max(0, round(20 + 110 * c + g(0, 2))),
                    "avg_speed_kmh": round(max(0.0, 62 * (1 - 0.7 * c) * boost + g(0, 1.0)), 2),
                    "congestion_score": round(c, 3)}
        if s.sensor_type == "power_meter":
            cap = CAPACITY_KW[z]
            h = self.local_hour(now)
            load = cap * (0.45 + 0.2 * math.sin((h - 6) / 24 * 2 * math.pi)) + g(0, 3)
            grid = next((a for a, (t, zz) in ACTUATORS.items() if t == "grid_switch" and zz == z), None)
            if not self.grid_connected[z] and grid not in self.stuck_actuators:
                load = abs(g(0, 0.5))
            return {"load_kw": round(max(0.0, load), 2), "capacity_kw": cap}
        if s.sensor_type == "grid_meter":
            return {"frequency_hz": round(50 + g(0, 0.01), 4), "voltage_v": round(230 + g(0, 0.8), 2)}
        raise ValueError(s.sensor_type)

    # ---------- envelopes
    def envelope(self, s: MockSensor, value: dict[str, Any], now: datetime, key: str | None = None) -> dict[str, Any]:
        s.seq += 1
        env = {"contract_version": "1.0", "sensor_id": s.sensor_id, "sensor_type": s.sensor_type,
               "zone_id": s.zone_id, "timestamp": iso(now), "sequence_no": s.seq, "value": value,
               "sequence_reset": s.reset_pending}
        s.reset_pending = False
        signed = sign_envelope(env, key or self.key)
        s.last_envelopes.append(signed)
        return signed

    def _apply_override(self, s: MockSensor, value: dict[str, Any]) -> dict[str, Any]:
        o = self.overrides.get(s.sensor_id)
        if o is None:
            return value
        o.applied += 1
        if o.kind == "fixed":
            return {**value, **o.values}
        if o.kind == "stuck":
            if not o.values:
                o.values = dict(value)
            return dict(o.values)
        if o.kind == "drift" and o.field_:
            return {**value, o.field_: round(value[o.field_] + o.step * o.applied, 4)}
        if o.kind == "spike":
            del self.overrides[s.sensor_id]
            return {**value, **o.values}
        return value

    def step(self, now: datetime | None = None) -> list[dict[str, Any]]:
        """Readings due at `now` (plus queued injected envelopes)."""
        now = now or self.clock.now()
        self.advance_physics(now)
        out, self.queue = self.queue, []
        if self.silence_all:
            return []
        for s in self.sensors.values():
            if s.interval is None or s.sensor_id in self.silenced:
                continue
            o = self.overrides.get(s.sensor_id)
            interval = o.interval if o and o.interval else s.interval
            if s.next_due is not None and now < s.next_due:
                continue
            # first reading immediately, then a random phase so sensors do not all report together
            phase = self.rng.uniform(0.5, 1.0) if s.next_due is None else 1.0
            s.next_due = now + timedelta(seconds=interval * phase)
            value = self._apply_override(s, self.true_value(s, now))
            key = None
            if self.bad_hmac.get(s.sensor_id, 0) > 0:
                self.bad_hmac[s.sensor_id] -= 1
                key = "not-the-twin-key"
            out.append(self.envelope(s, value, now, key))
        self._remember(out)
        return out

    def _remember(self, envs: list[dict[str, Any]]) -> None:
        for e in envs:
            if len(self.buffer) == self.buffer.maxlen:
                self.buffer_offset += 1
            self.buffer.append(e)

    def since(self, cursor: int) -> tuple[int, list[dict[str, Any]]]:
        start = max(0, cursor - self.buffer_offset)
        items = list(self.buffer)[start:]
        return self.buffer_offset + len(self.buffer), items

    def emit_call(self, zone: str, incident_type: str, caller_id: str | None = None,
                  call_id: str | None = None) -> dict[str, Any]:
        s = self.sensors[f"ec-gw-{zone.split('-')[1]}"]
        value = {"call_id": call_id or f"call-{secrets.token_hex(4)}", "incident_type": incident_type,
                 "caller_id": caller_id or f"caller-{secrets.token_hex(3)}"}
        env = self.envelope(s, value, self.clock.now())
        self.last_call = env
        self.queue.append(env)
        return env

    # ---------- injector
    def inject(self, kind: str, p: dict[str, Any]) -> dict[str, Any]:
        sid = p.get("sensor_id")
        if kind == "fake_flood":
            sid = sid or "wl-port-03"
            self.overrides[sid] = Override("fixed", {"level_m": float(p.get("level_m", 1.80))})
        elif kind == "spike":
            sid = sid or "wl-port-03"
            stype = self.sensors[sid].sensor_type
            fieldname = p.get("field") or {"water_level": "level_m", "air_quality": "aqi",
                                           "flow_meter": "flow_rate_m3s"}.get(stype, "")
            base = self.true_value(self.sensors[sid], self.clock.now())[fieldname]
            self.overrides[sid] = Override("spike", {fieldname: p.get("value", round(base * 3, 4))})
        elif kind == "stuck":
            sid = sid or "wl-port-03"
            o = Override("stuck", interval=float(p["interval_s"]) if "interval_s" in p else None)
            if "value" in p:
                o.values = {**self.true_value(self.sensors[sid], self.clock.now()), **p["value"]}
            self.overrides[sid] = o
        elif kind == "replay":
            sid = sid or "wl-port-03"
            n = int(p.get("count", 1))
            self.queue.extend(list(self.sensors[sid].last_envelopes)[-n:])
        elif kind == "bad_hmac":
            sid = sid or "wl-port-03"
            self.bad_hmac[sid] = int(p.get("count", 1))
        elif kind == "call_flood":
            zone = p.get("zone_id", "zone-08")
            for _ in range(int(p.get("count", 8))):
                self.emit_call(zone, p.get("incident_type", "medical"))
        elif kind == "call":
            self.emit_call(p.get("zone_id", "zone-07"), p.get("incident_type", "medical"), p.get("caller_id"),
                           p.get("call_id"))
        elif kind == "duplicate_call":
            if self.last_call is None:
                self.emit_call(p.get("zone_id", "zone-07"), "medical")
            assert self.last_call is not None
            v = self.last_call["value"]
            self.emit_call(self.last_call["zone_id"], v["incident_type"], v["caller_id"], v["call_id"])
        elif kind == "silence":
            if sid:
                self.silenced.add(sid)
            else:
                self.silence_all = True
        elif kind == "fire_in_sea":
            self.emit_call("zone-12", "fire")
        elif kind == "coordinated":
            zone = p.get("zone_id", "zone-08")
            spoof = {"water_level": {"level_m": 1.6}, "air_quality": {"aqi": 350.0, "smoke": True},
                     "traffic_camera": {"congestion_score": 0.95, "avg_speed_kmh": 8.0}}
            for s in self.sensors.values():
                if s.zone_id == zone and s.sensor_type in spoof:
                    self.overrides[s.sensor_id] = Override("fixed", spoof[s.sensor_type])
        elif kind == "valve_stuck":
            self.stuck_actuators.add(p.get("actuator_id", "valve-port-12"))
        elif kind == "slow_drift":
            sid = sid or "wl-port-03"
            self.overrides[sid] = Override("drift", step=float(p.get("step", 0.002)), field_=p.get("field", "level_m"))
        elif kind == "real_flood":
            for z in ZONES:
                self.rain_target[z] = float(p.get("rainfall_mm_h", 40))
        elif kind == "sequence_reset":
            targets = [self.sensors[sid]] if sid else list(self.sensors.values())
            for s in targets:
                s.seq = 0
                s.reset_pending = True
        elif kind == "clear":
            self.overrides.clear()
            self.bad_hmac.clear()
            self.silenced.clear()
            self.silence_all = False
            self.stuck_actuators.clear()
            if p.get("weather", False):
                self.rain_target = {z: 0.0 for z in ZONES}
        else:
            raise KeyError(kind)
        return {"injected": kind, "params": p}

    # ---------- actuator tools
    def tool(self, name: str, call: dict[str, Any]) -> dict[str, Any]:
        now = self.clock.now()
        aid = call.get("actuator_id", "")
        params = call.get("params") or {}
        self.tool_log.append({"tool": name, "call": call, "ts": iso(now)})
        kind, zone = ACTUATORS.get(aid, (None, call.get("zone_id")))
        if name in ("isolate_sensor", "quarantine_device", "clear_quarantine"):
            target = params.get("device_id", aid)
            if name == "isolate_sensor":
                self.isolated.add(target)
            elif name == "quarantine_device":
                self.quarantined.add(target)
            else:
                self.isolated.discard(target)
                self.quarantined.discard(target)
            return {"status": "ok", "current_state": {"device_id": target, "state": name}, "reverts_at": None}
        if name == "set_valve_state" and kind == "valve" and zone:
            st = params.get("state")
            if st not in ("open", "closed"):
                return {"status": "rejected", "current_state": {}, "reverts_at": None}
            self.valve_closed[zone] = st == "closed"  # a stuck valve still *says* ok
            return {"status": "ok", "current_state": {"state": st}, "reverts_at": None}
        if name == "set_grid_state" and kind == "grid_switch" and zone:
            st = params.get("state")
            if st not in ("connected", "disconnected"):
                return {"status": "rejected", "current_state": {}, "reverts_at": None}
            self.grid_connected[zone] = st == "connected"
            return {"status": "ok", "current_state": {"state": st}, "reverts_at": None}
        if name == "set_signal" and kind == "traffic_signal" and zone:
            dur = float(params.get("duration_s", 60))
            if params.get("state") == "green":
                self.green_until[zone] = now + timedelta(seconds=dur)
            return {"status": "ok", "current_state": {"state": params.get("state")},
                    "reverts_at": iso(now + timedelta(seconds=dur))}
        if name == "dispatch_unit":
            unit = f"{params.get('unit_type', 'unit')}-{secrets.token_hex(2)}"
            state = {"unit_id": unit, "eta_s": 240, "incident_id": call.get("incident_id")}
            return {"status": "ok", "current_state": state, "reverts_at": None}
        return {"status": "rejected", "current_state": {"error": f"unsupported {name} on {aid}"}, "reverts_at": None}
