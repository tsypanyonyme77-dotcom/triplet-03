"""Correlator: turns verdicts, ingest errors and actuator decisions into signals, matches attack signatures over
sliding windows, raises zone threat levels, opens incidents and plans proportionate responses."""

from __future__ import annotations

import secrets
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from guardian.audit.logger import AuditLogger
from guardian.clock import Clock, iso
from guardian.config import Pattern
from guardian.models import Signal, Status, ThreatLevel, Verdict
from guardian.threat.alerts import AlertBus
from guardian.threat.attack_catalogue import AttackCatalogue
from guardian.threat.threat_level import ThreatLevels

BENIGN = {"corroboration_pass", "real_incident"}
SPOOF_REASONS = {"rate_of_change", "impossible_location", "zscore_outlier", "unit_mismatch"}


class Containment(Protocol):
    def can_isolate(self, zone_id: str | None) -> bool: ...

    async def isolate(self, sensor_id: str, zone_id: str | None, reason: str,
                      evidence: list[dict[str, Any]]) -> object: ...

    async def quarantine(self, device_id: str, device_type: str, reason: str, zone_id: str | None = None,
                         evidence: list[dict[str, Any]] | None = None) -> object: ...


class Freezer(Protocol):
    def freeze(self, sensor_id: str) -> None: ...


@dataclass
class Response:
    pattern: str
    action: str  # isolate_sensor | quarantine_caller | freeze_baseline | alert
    target: str | None
    zone_id: str | None
    evidence: list[dict[str, Any]] = field(default_factory=list)
    response: str = ""


@dataclass
class Incident:
    incident_id: str
    pattern: str
    zone_id: str | None
    key: str
    opened_at: datetime
    last_seen: datetime
    evidence: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"incident_id": self.incident_id, "pattern": self.pattern, "zone_id": self.zone_id,
                "key": self.key, "opened_at": iso(self.opened_at), "last_seen": iso(self.last_seen),
                "evidence": self.evidence[-5:]}


def _ev(s: Signal) -> dict[str, Any]:
    return {"signal": s.type, "ts": iso(s.ts), "zone_id": s.zone_id, "device_id": s.device_id,
            "source": s.source, **s.evidence}


class Correlator:
    def __init__(self, catalogue: AttackCatalogue, levels: ThreatLevels, alerts: AlertBus, clock: Clock,
                 audit: AuditLogger, quiet_period_s: float) -> None:
        self.cat, self.levels, self.alerts, self.clock, self.audit = catalogue, levels, alerts, clock, audit
        self.quiet = quiet_period_s
        self.containment: Containment | None = None
        self.baseline: Freezer | None = None
        self.signals: deque[Signal] = deque(maxlen=20_000)
        self.incidents: dict[str, Incident] = {}
        self._fired: dict[tuple[str, str], datetime] = {}
        self.flagged_sources: set[str] = set()

    # ---------- signal intake
    def add(self, sig: Signal) -> list[Response]:
        self.signals.append(sig)
        if sig.type not in BENIGN:
            self.levels.touch(sig.zone_id)
        out: list[Response] = []
        for name, p in self.cat.listening(sig.type):
            out += self._generic(name, p, sig)
        if sig.type in {"corroboration_fail", "corroboration_pass"}:
            out += self._compromised_twin()
        if sig.type in {"real_incident", "reading_failed"}:
            out += self._attack_during_incident()
        return out

    def _window(self, types: set[str] | list[str], window_s: float) -> list[Signal]:
        now = self.clock.now()
        return [s for s in self.signals if s.type in types and (now - s.ts).total_seconds() <= window_s]

    @staticmethod
    def _key(p: Pattern, s: Signal) -> str | None:
        return {"zone": s.zone_id, "device": s.device_id, "source": s.source}[p.group_by]

    def _cooldown_ok(self, name: str, key: str, window_s: float) -> bool:
        last = self._fired.get((name, key))
        now = self.clock.now()
        if last is not None and (now - last).total_seconds() < window_s:
            return False
        self._fired[(name, key)] = now
        return True

    def _generic(self, name: str, p: Pattern, sig: Signal) -> list[Response]:
        key = self._key(p, sig)
        if key is None:
            return []
        hits = [s for s in self._window(p.signals, p.window_s) if self._key(p, s) == key]
        count = len({getattr(s, f"{p.distinct}_id" if p.distinct == "device" else p.distinct) for s in hits}
                    if p.distinct else hits)
        if count < p.threshold or not self._cooldown_ok(name, key, p.window_s):
            return []
        return self._fire(name, p, key, sig, hits)

    def _fire(self, name: str, p: Pattern, key: str, sig: Signal, hits: list[Signal]) -> list[Response]:
        zone = sig.zone_id
        if p.raises_to:
            self.levels.raise_to(zone, ThreatLevel(p.raises_to), name)
        now = self.clock.now()
        inc = self.incidents.get(f"{name}:{key}")
        evidence = [_ev(s) for s in hits[-10:]]
        if inc is None:
            inc = Incident(f"inc-{secrets.token_hex(4)}", name, zone, key, now, now)
            self.incidents[f"{name}:{key}"] = inc
        inc.last_seen, inc.evidence = now, evidence
        responses: list[Response] = []
        if p.response == "isolate_and_rollback" and sig.device_id:
            responses.append(Response(name, "isolate_sensor", sig.device_id, zone, evidence, p.response))
        elif p.response == "block_and_quarantine_caller" and sig.source:
            responses.append(Response(name, "quarantine_caller", sig.source, zone, evidence, p.response))
        elif p.response == "alert_and_freeze_baseline" and sig.device_id:
            responses.append(Response(name, "freeze_baseline", sig.device_id, zone, evidence, p.response))
        elif p.response == "block_and_flag_source" and sig.source:
            self.flagged_sources.add(sig.source)
        responses.append(Response(name, "alert", key, zone, evidence, p.response))  # after the action it reports
        return responses

    def _compromised_twin(self) -> list[Response]:
        found = self.cat.special("compromised_twin")
        if not found:
            return []
        name, p = found
        sigs = self._window({"corroboration_fail", "corroboration_pass"}, p.window_s)
        zones = {s.zone_id for s in sigs}
        failing = {s.zone_id for s in sigs if s.type == "corroboration_fail"}
        if len(zones) < p.min_zones or len(failing) / len(zones) < p.fraction:
            return []
        if not self._cooldown_ok(name, "city", p.window_s):
            return []
        ev = [{"zones_evaluated": sorted(z for z in zones if z), "zones_failing": sorted(z for z in failing if z)}]
        self.incidents[f"{name}:city"] = Incident(f"inc-{secrets.token_hex(4)}", name, None, "city",
                                                  self.clock.now(), self.clock.now(), ev)
        return [Response(name, "alert", "city", None, ev, p.response)]

    def _attack_during_incident(self) -> list[Response]:
        found = self.cat.special("attack_during_incident")
        if not found:
            return []
        name, p = found
        real = self._window({"real_incident"}, p.window_s)
        bad = self._window({"reading_failed"}, p.window_s)
        out: list[Response] = []
        for zr in {s.zone_id for s in real}:
            for zb in {s.zone_id for s in bad if s.zone_id != zr}:
                key = f"{zr}|{zb}"
                if zr and zb and self._cooldown_ok(name, key, p.window_s):
                    ev = [{"real_incident_zone": zr, "untrusted_zone": zb}]
                    out.append(Response(name, "alert", key, zb, ev, p.response))
        return out

    # ---------- translators
    def observe_verdict(self, v: Verdict) -> list[Response]:
        base = {"zone_id": v.zone_id, "device_id": v.sensor_id, "source": v.sensor_id, "ts": self.clock.now()}
        ev = {"verdict_id": v.verdict_id, "reasons": v.reasons}
        sigs: list[Signal] = []
        reasons = set(v.reasons)
        for r in ("replay", "hmac_invalid", "call_flood", "rate_exceeded", "slow_drift"):
            if r in reasons:
                sigs.append(Signal(type=r, evidence=ev, **base))
        status = v.raw_status or v.status  # containment-forced untrusted is not a new failure
        if status == Status.untrusted:
            sigs.append(Signal(type="reading_failed", evidence=ev, **base))
            corro_fail = any(r.startswith("no_") and r.endswith("_corroboration") for r in reasons)
            if v.sensor_type != "emergency_call" and (corro_fail or reasons & SPOOF_REASONS) and \
                    not reasons & {"replay", "hmac_invalid", "timestamp_skew"}:
                sigs.append(Signal(type="spoofing", evidence=ev, **base))
        if any(lr.layer == "L5_corroboration" for lr in v.layer_results):
            failed = any(lr.layer == "L5_corroboration" and lr.severity == "strong" for lr in v.layer_results)
            sigs.append(Signal(type="corroboration_fail" if failed else "corroboration_pass", evidence=ev, **base))
        if v.status == Status.trusted and v.corroborated and v.notable:
            sigs.append(Signal(type="real_incident", evidence=ev, **base))
        out: list[Response] = []
        for s in sigs:
            out += self.add(s)
        return out

    def observe_ingest_error(self, code: str, source: str | None, zone_id: str | None,
                             detail: str) -> list[Response]:
        return self.add(Signal(type=code, ts=self.clock.now(), zone_id=zone_id, device_id=source, source=source,
                               evidence={"detail": detail}))

    def observe_decision(self, caller: str, actuator_id: str, zone_id: str | None, reasons: list[str],
                         call_id: str) -> list[Response]:
        injection = {"trust_ref_missing", "trust_ref_unknown", "rate_limited", "odd_hour_action"}
        hit = sorted(set(reasons) & injection)
        if not hit:
            return []
        return self.add(Signal(type="command_injection", ts=self.clock.now(), zone_id=zone_id,
                               device_id=actuator_id, source=caller,
                               evidence={"call_id": call_id, "reasons": hit}))

    # ---------- execution
    async def execute(self, responses: list[Response]) -> None:
        for r in responses:
            try:
                if r.action == "alert":
                    self.alerts.raise_alert(r.pattern, r.zone_id, r.evidence, self.cat.suggested(r.response))
                elif r.action == "isolate_sensor" and self.containment and r.target:
                    await self.containment.isolate(r.target, r.zone_id, r.pattern, r.evidence)
                elif r.action == "quarantine_caller" and self.containment and r.target:
                    await self.containment.quarantine(r.target, "caller", r.pattern, r.zone_id, r.evidence)
                elif r.action == "freeze_baseline" and self.baseline and r.target:
                    self.baseline.freeze(r.target)
                    self.audit.emit("action", f"baseline frozen for {r.target}", sensor_id=r.target,
                                    zone_id=r.zone_id, data={"kind": "freeze_baseline", "pattern": r.pattern})
            except Exception as e:  # fail safe: a response failure never breaks ingest
                self.audit.emit("error", f"response {r.action} failed: {e}", zone_id=r.zone_id,
                                data={"kind": "response_failed", "pattern": r.pattern})

    def planned_action(self, responses: list[Response]) -> str | None:
        for r in responses:
            if r.action == "isolate_sensor" and self.containment and self.containment.can_isolate(r.zone_id):
                return "isolate_sensor"
        return None

    def tick(self) -> None:
        self.levels.tick()
        now = self.clock.now()
        for k, inc in list(self.incidents.items()):
            if (now - inc.last_seen).total_seconds() >= self.quiet:
                del self.incidents[k]

    def open_incidents(self) -> list[dict[str, Any]]:
        return [i.as_dict() for i in self.incidents.values()]
