"""Verdict engine: builds, signs, stores (SQLite + LRU), publishes (WS) and audits every verdict."""

from __future__ import annotations

import secrets
from datetime import timedelta
from typing import Protocol

from guardian.adapters.schemas import VerdictOut
from guardian.adapters.schemas.wire import verdict_payload
from guardian.audit.logger import AuditLogger
from guardian.audit.timeline_emitter import TimelineEmitter
from guardian.clock import Clock
from guardian.ingest.state_store import HistEntry, StateStore
from guardian.models import LayerResult, Reading, Status, ThreatLevel, Verdict
from guardian.trust.signer import Signer


class Learner(Protocol):
    def learn(self, reading: Reading) -> None: ...


class VerdictEngine:
    def __init__(self, state: StateStore, signer: Signer, clock: Clock, ttl_s: float, emitter: TimelineEmitter,
                 audit: AuditLogger) -> None:
        self.state, self.signer, self.clock, self.ttl = state, signer, clock, ttl_s
        self.emitter, self.audit = emitter, audit
        self.learners: list[Learner] = []

    def build(self, *, sensor_id: str, sequence_no: int | None, status: Status, score: float,
              reasons: list[str], results: list[LayerResult], threat: ThreatLevel = ThreatLevel.normal,
              sensor_type: str | None = None, zone_id: str | None = None, **extra: object) -> Verdict:
        now = self.clock.now()
        return Verdict(verdict_id=f"verdict-{secrets.token_hex(6)}", sensor_id=sensor_id, sequence_no=sequence_no,
                       sensor_type=sensor_type, zone_id=zone_id, status=status, trust_score=score,
                       reasons=reasons, layer_results=results, threat_level=threat, ts=now,
                       expires_at=now + timedelta(seconds=self.ttl), **extra)

    def sign(self, v: Verdict) -> Verdict:
        v.signature = self.signer.sign(verdict_payload(v))
        return v

    def verify(self, v: Verdict) -> bool:
        return self.signer.verify(verdict_payload(v), v.signature)

    def publish(self, v: Verdict, reading: Reading | None = None) -> Verdict:
        """reading is set only when the reading passed the hard gates and belongs in history."""
        self.sign(v)
        self.state.put_verdict(v)
        if reading is not None:
            s = self.state.get(reading.sensor_id)
            if s is not None:
                s.latest_verdict = v
                s.history.append(HistEntry(reading.ts, reading.value, v.status))
                if v.status == Status.trusted:
                    self.state.set_lkg(reading)
                    for learner in self.learners:
                        learner.learn(reading)
        wire = VerdictOut.from_verdict(v).model_dump()
        self.emitter.publish("verdicts", {"type": "verdict", "verdict": wire})
        self.audit.emit("verdict",
                        f"{v.status.value} {v.sensor_id}#{v.sequence_no} score={v.trust_score}"
                        + (f" [{', '.join(v.reasons)}]" if v.reasons else ""),
                        sensor_id=v.sensor_id, zone_id=v.zone_id,
                        data={"kind": "verdict", "verdict_id": v.verdict_id, "status": v.status.value,
                              "trust_score": v.trust_score, "reasons": v.reasons, "action_taken": v.action_taken,
                              "threat_level": v.threat_level.value})
        return v

    def unknown(self, sensor_id: str, reason: str, sequence_no: int | None = None, zone_id: str | None = None,
                sensor_type: str | None = None, threat: ThreatLevel = ThreatLevel.normal) -> Verdict:
        v = self.build(sensor_id=sensor_id, sequence_no=sequence_no, status=Status.unknown, score=0.0,
                       reasons=[reason], results=[LayerResult(layer="L6_liveness", passed=False, severity="hard",
                                                              reason_code=reason, detail=reason)],
                       threat=threat, zone_id=zone_id, sensor_type=sensor_type)
        return self.publish(v)

    def reissue(self, old: Verdict, status: Status | None = None, extra_reason: str | None = None,
                threat: ThreatLevel | None = None) -> Verdict:
        """Fresh id/ts/expiry for an expired verdict about the same (still latest) reading."""
        st = status or old.status
        reasons = old.reasons + ([extra_reason] if extra_reason and extra_reason not in old.reasons else [])
        v = self.build(sensor_id=old.sensor_id, sequence_no=old.sequence_no, status=st,
                       score=old.trust_score if st == old.status else min(old.trust_score, 0.39),
                       reasons=reasons, results=old.layer_results, threat=threat or old.threat_level,
                       sensor_type=old.sensor_type, zone_id=old.zone_id, raw_status=old.raw_status,
                       self_consistent=old.self_consistent, corroborated=old.corroborated,
                       corroborating_sources=old.corroborating_sources, notable=old.notable, value=old.value,
                       action_taken=None)
        return self.publish(v)
