"""Effect verifier: compares what was ordered with what happened, using sensors independent of the actuator.

Contains the tiny expectation DSL (fixed predicates, no eval): drop_pct >= N, rise_pct >= N, value <= N,
value >= N, present. Failure types: no_effect, wrong_effect, partial_effect, late_effect,
reply_contradicts_order, unauthorised_effect, reverted_early. An untrusted verify sensor gives `unknown`."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from guardian.audit.logger import AuditLogger
from guardian.clock import Clock, iso
from guardian.config import Expectation, Policies
from guardian.containment.manager import ContainmentManager
from guardian.ingest.state_store import StateStore
from guardian.models import ActuatorCall, Reading, Status
from guardian.threat.alerts import AlertBus
from guardian.threat.attack_catalogue import AttackCatalogue

_RE = re.compile(r"^\s*(drop_pct|rise_pct|value)\s*(>=|<=)\s*(-?\d+(?:\.\d+)?)\s*$")
CUT_ACTIONS = {"valve": "set_valve_state", "grid_switch": "set_grid_state"}  # effects that look like a cut


class DslError(ValueError):
    pass


@dataclass(frozen=True)
class Predicate:
    metric: str  # drop_pct | rise_pct | value | present
    op: str = ">="
    threshold: float = 0.0

    def measure(self, before: float | None, after: float) -> float | None:
        if self.metric == "value":
            return after
        if before is None:
            return None
        if self.metric == "drop_pct":
            return (before - after) / before * 100 if before > 0 else 0.0
        return (after - before) / before * 100 if before > 0 else (100.0 if after > 0 else 0.0)

    def holds(self, before: float | None, after: float) -> bool:
        m = self.measure(before, after)
        if m is None:
            return False
        return m >= self.threshold if self.op == ">=" else m <= self.threshold

    def progress(self, before: float | None, after: float) -> float:
        """Fraction of the way to the target, for partial_effect."""
        if before is None:
            return 0.0
        if self.metric == "value":
            span = before - self.threshold
            return 1.0 if span == 0 else max(0.0, (before - after) / span)
        m = self.measure(before, after) or 0.0
        return max(0.0, m / self.threshold) if self.threshold else 1.0


def parse_expect(expr: str) -> Predicate:
    if expr.strip() == "present":
        return Predicate("present")
    m = _RE.match(expr)
    if not m:
        raise DslError(f"unsupported expectation {expr!r}; use drop_pct/rise_pct/value with >= or <=, or present")
    metric, op, num = m.groups()
    if metric in ("drop_pct", "rise_pct") and op != ">=":
        raise DslError(f"{metric} only supports >=")
    return Predicate(metric, op, float(num))


def spec_for(policies: Policies, call: ActuatorCall) -> Expectation | None:
    by_value = policies.expectations.get(call.action, {})
    value = call.params.get("state", call.params.get("unit_type"))
    return by_value.get(str(value)) or by_value.get("any")


@dataclass
class Pending:
    call: ActuatorCall
    spec: Expectation
    pred: Predicate
    sensors: list[str]
    field: str
    before: float | None
    others_before: dict[str, float]
    started: datetime
    deadline: datetime
    late_until: datetime
    hold_until: datetime | None = None
    state: str = "pending"  # pending | late_watch | holding
    zone_id: str | None = None


class EffectVerifier:
    def __init__(self, policies: Policies, state: StateStore, containment: ContainmentManager, alerts: AlertBus,
                 audit: AuditLogger, clock: Clock) -> None:
        self.p, self.state, self.containment = policies, state, containment
        self.alerts, self.audit, self.clock = alerts, audit, clock
        self.pending: list[Pending] = []
        self.results: list[dict[str, Any]] = []
        self.last_call: dict[str, datetime] = {}
        self.quarantine_watch: list[tuple[str, datetime, datetime]] = []
        self.explained_until: dict[str, tuple[str, datetime]] = {}  # sensor -> (call_id, until)
        for spec_map in policies.expectations.values():  # fail at startup on a bad expectation
            for spec in spec_map.values():
                parse_expect(spec.expect)

    # ---------- helpers
    def _trusted(self, sensor_id: str) -> bool:
        """Is this verify sensor's reading usable as independent evidence of a physical effect?

        A `trusted` sensor always is. A `suspect` one counts too *only when it is self-consistent* (no range,
        semantic, rate, flatline or drift problem): in a raised-threat zone the scorer caps a sensor to
        `suspect` for lack of corroboration, and corroboration is deliberately skipped for a sensor whose
        change we ourselves explained with the in-flight order — so without this, effect verification could
        never conclude in exactly the zones (elevated / under_attack) where it matters most. An `untrusted`
        or `unknown` sensor is never usable, so we still do not accuse the actuator on its word."""
        s = self.state.get(sensor_id)
        if not (s and not s.stale and s.latest_verdict and not self.containment.is_contained(sensor_id)):
            return False
        v = s.latest_verdict
        return v.status == Status.trusted or (v.status == Status.suspect and v.self_consistent)

    def _value(self, sensor_id: str, field_: str) -> float | None:
        s = self.state.get(sensor_id)
        v = s.latest_reading.value.get(field_) if s and s.latest_reading else None
        return float(v) if isinstance(v, int | float) and not isinstance(v, bool) else None

    def _mean(self, sensors: list[str], field_: str) -> float | None:
        vals = [v for s in sensors if (v := self._value(s, field_)) is not None]
        return sum(vals) / len(vals) if vals else None

    def explains(self, sensor_id: str) -> str | None:
        """call_id of an in-flight order whose expected effect covers this sensor (suppresses L4 alarms)."""
        for p in self.pending:
            if sensor_id in p.sensors:
                return p.call.call_id
        grace = self.explained_until.get(sensor_id)
        if grace and self.clock.now() <= grace[1]:
            return grace[0]
        return None

    def _result(self, p: Pending | None, call: ActuatorCall, outcome: str, detail: str,
                zone_id: str | None) -> dict[str, Any]:
        res = {"call_id": call.call_id, "actuator_id": call.actuator_id, "action": call.action,
               "outcome": outcome, "detail": detail, "ts": iso(self.clock.now())}
        self.results.append(res)
        self.audit.emit("action", f"effect check {call.actuator_id}: {outcome}", actuator_id=call.actuator_id,
                        zone_id=zone_id, data={"kind": "effect_verification", **res})
        return res

    async def _fail(self, call: ActuatorCall, spec: Expectation, failure: str, detail: str,
                    zone_id: str | None) -> None:
        self._result(None, call, failure, detail, zone_id)
        evidence = [{"call_id": call.call_id, "failure": failure, "detail": detail}]
        if spec.on_fail == "actuator_failure":
            await self.containment.flag_unreliable(call.actuator_id, zone_id, failure, evidence)
        self.alerts.raise_alert(spec.on_fail, zone_id, evidence, AttackCatalogue.suggested("use_backup_actuator"),
                                actuator_id=call.actuator_id)

    # ---------- intake
    async def expect(self, call: ActuatorCall, reply: dict[str, Any]) -> list[str]:
        """Register the expectation for a forwarded call; returns immediate failure reasons."""
        self.last_call[call.actuator_id] = self.clock.now()
        spec = spec_for(self.p, call)
        actuator = self.p.actuators.get(call.actuator_id)
        zone = (actuator.zone_id if actuator else None) or call.zone_id
        wanted = call.params.get("state")
        got = (reply.get("current_state") or {}).get("state")
        if wanted is not None and got is not None and got != wanted:
            if spec:
                await self._fail(call, spec, "reply_contradicts_order", f"asked {wanted}, Twin reports {got}", zone)
            return ["reply_contradicts_order"]
        if spec is None:
            return []
        pred = parse_expect(spec.expect)
        if pred.metric == "present":
            cur = reply.get("current_state") or {}
            missing = [f for f in spec.verify_with if f.startswith("twin_reply.")
                       and reply.get(f.split(".", 1)[1]) is None and cur.get(f.split(".", 1)[1]) is None]
            if missing:
                await self._fail(call, spec, "no_effect", f"reply lacks {', '.join(missing)}", zone)
                return ["no_effect"]
            self._result(None, call, "verified", "reply carries " + ", ".join(spec.verify_with), zone)
            return []
        sensors = actuator.verify_sensors if actuator else []
        field_ = spec.verify_with[0]
        now = self.clock.now()
        first = self.state.get(sensors[0]) if sensors else None
        stype = first.sensor_type if first else None
        others = {s.sensor_id: v for s in self.state.sensors.values()
                  if s.sensor_type == stype and s.sensor_id not in sensors
                  and (v := self._value(s.sensor_id, field_)) is not None}
        p = Pending(call, spec, pred, sensors, field_, self._mean(sensors, field_), others, now,
                    now + timedelta(seconds=spec.within_s),
                    now + timedelta(seconds=spec.within_s + self.p.verification.late_window_s), zone_id=zone)
        if spec.check_reverts_at and "duration_s" in call.params:
            p.hold_until = now + timedelta(seconds=float(call.params["duration_s"]))
            reverts = reply.get("reverts_at")
            if reverts:
                rv = datetime.fromisoformat(str(reverts).replace("Z", "+00:00"))
                if rv < p.hold_until - timedelta(seconds=self.p.verification.revert_tolerance_s):
                    await self._fail(call, spec, "reverted_early",
                                     f"Twin says reverts_at {reverts}, ordered until {iso(p.hold_until)}", zone)
                    return ["reverted_early"]
        self.pending.append(p)
        return []

    def watch_quarantine(self, device_id: str) -> None:
        spec = self.p.expectations.get("quarantine_device", {}).get("any")
        if spec:
            now = self.clock.now()
            self.quarantine_watch.append((device_id, now, now + timedelta(seconds=spec.within_s)))

    # ---------- periodic check
    async def tick(self) -> None:
        now = self.clock.now()
        for p in list(self.pending):
            await self._check(p, now)
        for item in list(self.quarantine_watch):
            device, since, deadline = item
            if now < deadline:
                continue
            self.quarantine_watch.remove(item)
            s = self.state.get(device)
            used = bool(s and s.latest_verdict and s.latest_verdict.ts >= since
                        and s.latest_verdict.status == Status.trusted)
            call = ActuatorCall(call_id=f"quarantine-{device}", actuator_id=device, action="quarantine_device",
                                requesting_layer="guardian")
            if used:
                spec = self.p.expectations["quarantine_device"]["any"]
                await self._fail(call, spec, "no_effect", "quarantined device still served as trusted",
                                 s.zone_id if s else None)
            else:
                self._result(None, call, "verified", "no readings from the quarantined device used",
                             s.zone_id if s else None)

    async def _check(self, p: Pending, now: datetime) -> None:
        after = self._mean(p.sensors, p.field)
        trusted = bool(p.sensors) and all(self._trusted(s) for s in p.sensors)
        holds = after is not None and p.pred.holds(p.before, after)
        detail = f"{p.field}: {p.before} → {after}"
        if p.state == "holding":
            assert p.hold_until is not None
            if now >= p.hold_until - timedelta(seconds=self.p.verification.revert_tolerance_s):
                self.pending.remove(p)
                return
            if trusted and not holds:
                self.pending.remove(p)
                await self._fail(p.call, p.spec, "reverted_early",
                                 f"effect vanished at {iso(now)}, ordered until {iso(p.hold_until)}", p.zone_id)
            return
        if holds and trusted:
            if p.state == "late_watch":
                self.pending.remove(p)
                await self._fail(p.call, p.spec, "late_effect",
                                 f"{detail} after {(now - p.started).total_seconds():.0f}s "
                                 f"(> {p.spec.within_s:.0f}s)", p.zone_id)
                return
            self._result(p, p.call, "verified", detail, p.zone_id)
            for sid in p.sensors:  # the new level stays explained while the dynamics settle
                self.explained_until[sid] = (p.call.call_id, now + timedelta(seconds=p.spec.within_s))
            if p.hold_until and now < p.hold_until:
                p.state = "holding"
            else:
                self.pending.remove(p)
            return
        if p.state == "late_watch":
            if now >= p.late_until:
                self.pending.remove(p)
            return
        if now < p.deadline:
            return
        if not trusted or after is None:
            self.pending.remove(p)
            self._result(p, p.call, "unknown",
                         f"verification sensor(s) {p.sensors} not trusted at check time; not accusing actuator",
                         p.zone_id)
            return
        moved = [sid for sid, b in p.others_before.items()
                 if (v := self._value(sid, p.field)) is not None and p.pred.holds(b, v)]
        if moved:
            self.pending.remove(p)
            await self._fail(p.call, p.spec, "wrong_effect", f"{detail}; but {moved} changed instead", p.zone_id)
            return
        progress = p.pred.progress(p.before, after)
        kind = "partial_effect" if progress >= self.p.verification.partial_min_progress else "no_effect"
        p.state = "late_watch"
        await self._fail(p.call, p.spec, kind, f"{detail} ({progress:.0%} of expected) within "
                                               f"{p.spec.within_s:.0f}s", p.zone_id)

    async def observe_reading(self, r: Reading, prev: dict[str, Any] | None) -> None:
        """unauthorised_effect: a verify sensor shows a cut-type effect against its last trusted value while
        no call was issued."""
        if prev is None:
            return
        now = self.clock.now()
        window = self.p.verification.unauthorised_window_s
        for aid, a in self.p.actuators.items():
            if r.sensor_id not in a.verify_sensors or a.type not in CUT_ACTIONS:
                continue
            last = self.last_call.get(aid)
            if last is not None and (now - last).total_seconds() <= window:
                continue
            for spec in self.p.expectations.get(CUT_ACTIONS[a.type], {}).values():
                pred = parse_expect(spec.expect)
                f = spec.verify_with[0]
                b, v = prev.get(f), r.value.get(f)
                if not isinstance(b, int | float) or not isinstance(v, int | float):
                    continue
                if pred.metric == "drop_pct":
                    hit = pred.holds(float(b), float(v)) and \
                        (float(b) - float(v)) / max(float(b), 1e-9) * 100 >= self.p.verification.unauthorised_drop_pct
                else:
                    hit = pred.holds(float(b), float(v)) and not pred.holds(None, float(b))
                if hit:
                    self.last_call[aid] = now  # one alert per change
                    call = ActuatorCall(call_id=f"none-{aid}", actuator_id=aid, action=CUT_ACTIONS[a.type],
                                        requesting_layer="unknown")
                    await self._fail(call, spec, "unauthorised_effect",
                                     f"{r.sensor_id} {f}: {b} → {v} with no call to {aid}", a.zone_id)
