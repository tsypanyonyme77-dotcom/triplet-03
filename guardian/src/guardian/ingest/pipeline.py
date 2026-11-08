"""Pipeline: raw envelope → L1 → L2 → (L6, L3a, L3b, L4, L5) → score → verdict → correlate → contain.

Nothing here raises to the caller: errors become an audit event plus an `unknown` verdict (fail safe)."""

from __future__ import annotations

from typing import Any

from guardian.actuator_watch.effect_verifier import EffectVerifier
from guardian.audit.logger import AuditLogger
from guardian.clock import Clock
from guardian.config import GuardianConfig
from guardian.containment.manager import ContainmentManager
from guardian.detectors.authenticity import AuthenticityDetector
from guardian.detectors.base import L4, ok
from guardian.detectors.crosscheck import CrosscheckDetector
from guardian.detectors.dynamics import DynamicsDetector
from guardian.detectors.freshness import FreshnessDetector
from guardian.detectors.liveness_rate import LivenessDetector
from guardian.detectors.plausibility import PlausibilityDetector
from guardian.detectors.semantic_plausibility import SemanticDetector
from guardian.ingest.normalizer import normalize
from guardian.ingest.state_store import StateStore
from guardian.ingest.validator import IngestError
from guardian.models import LayerResult, Reading, Status, ThreatLevel, Verdict
from guardian.threat.correlator import Correlator
from guardian.threat.threat_level import ThreatLevels
from guardian.trust.scorer import Scorer
from guardian.trust.verdict_engine import VerdictEngine

EVENT_CLAIMS = {"rate_of_change", "zscore_outlier", "baseline_deviation"}


class Pipeline:
    def __init__(self, cfg: GuardianConfig, clock: Clock, state: StateStore, audit: AuditLogger,
                 l1: AuthenticityDetector, l2: FreshnessDetector, l3a: PlausibilityDetector,
                 l3b: SemanticDetector, l4: DynamicsDetector, l5: CrosscheckDetector, l6: LivenessDetector,
                 scorer: Scorer, engine: VerdictEngine, correlator: Correlator, containment: ContainmentManager,
                 levels: ThreatLevels, verifier: EffectVerifier) -> None:
        self.cfg, self.clock, self.state, self.audit = cfg, clock, state, audit
        self.l1, self.l2, self.l3a, self.l3b, self.l4, self.l5, self.l6 = l1, l2, l3a, l3b, l4, l5, l6
        self.scorer, self.engine, self.correlator = scorer, engine, correlator
        self.containment, self.levels, self.verifier = containment, levels, verifier

    async def ingest_many(self, items: list[Any], source: str = "twin") -> list[Verdict | IngestError]:
        return [await self.ingest(raw, source) for raw in items]

    async def ingest(self, raw: Any, source: str = "twin") -> Verdict | IngestError:
        try:
            return await self._ingest(raw, source)
        except IngestError as e:
            return e
        except Exception as e:  # fail safe: never crash, never trusted
            sid = raw.get("sensor_id") if isinstance(raw, dict) else None
            self.audit.emit("error", f"pipeline error: {type(e).__name__}: {e}"[:300],
                            sensor_id=sid if isinstance(sid, str) else None, data={"kind": "pipeline_error"})
            if isinstance(sid, str):
                return self.engine.unknown(sid, "internal_error")
            return IngestError("internal_error", "reading could not be processed")

    async def _reject(self, e: IngestError, raw: Any, source: str) -> IngestError:
        sid = raw.get("sensor_id") if isinstance(raw, dict) and isinstance(raw.get("sensor_id"), str) else None
        zone = raw.get("zone_id") if isinstance(raw, dict) and isinstance(raw.get("zone_id"), str) else None
        self.audit.emit("error", f"reading rejected: {e.code}: {e.message}"[:300], sensor_id=sid, zone_id=zone,
                        data={"kind": "ingest_error", **e.as_dict(), "source": source})
        await self.correlator.execute(self.correlator.observe_ingest_error(e.code, sid or source, zone, e.message))
        return e

    async def _ingest(self, raw: Any, source: str) -> Verdict | IngestError:
        try:
            env, r1 = self.l1.check_raw(raw)
        except IngestError as e:
            return await self._reject(e, raw, source)
        reading = normalize(env, self.cfg.sensors, source)
        threat = self.levels.get(reading.zone_id)
        self.audit.emit("reading", f"{reading.sensor_id}#{reading.sequence_no} {reading.value}"[:300],
                        sensor_id=reading.sensor_id, zone_id=reading.zone_id,
                        data={"kind": "reading", "sensor_type": reading.sensor_type,
                              "sequence_no": reading.sequence_no, "value": reading.value,
                              "sequence_reset": reading.sequence_reset})
        results: list[LayerResult] = [r1]
        if r1.passed:
            results += self.l2.check(reading)
        if any(not r.passed for r in results):
            return await self._finish(reading, results, threat, accepted=False)

        s = self.state.accept(reading, self.clock.now())
        if reading.sequence_reset:
            self.audit.emit("system", f"sequence reset accepted for {reading.sensor_id}",
                            sensor_id=reading.sensor_id, zone_id=reading.zone_id,
                            data={"kind": "sequence_reset", "sequence_no": reading.sequence_no})
        prev = s.lkg.value if s.lkg else None  # last trusted value, for unauthorised-effect checks
        checks = set(self.cfg.sensors.sensor_types[reading.sensor_type].checks)
        r6 = self.l6.check(reading)
        if any(r.severity == "hard" and not r.passed for r in r6):
            return await self._finish(reading, results + r6, threat, accepted=True, prev=prev)
        if "range" in checks:
            results += self.l3a.check(reading)
        if "semantic" in checks:
            results += self.l3b.check(reading)
        dyn = self.l4.check(reading) if "dynamics" in checks else []
        explained = self.verifier.explains(reading.sensor_id)
        if explained and any(not r.passed and r.reason_code in EVENT_CLAIMS for r in dyn):
            dyn = [r for r in dyn if r.passed or r.reason_code not in EVENT_CLAIMS]
            dyn.append(ok(L4, f"change explained by in-flight actuator call {explained}",
                          reason="explained_by_actuator"))
        results += dyn
        notable = self.l5.is_notable(reading)
        dyn_flag = any(not r.passed for r in dyn)
        claim = notable or any(not r.passed and r.reason_code in EVENT_CLAIMS for r in dyn)
        agree = 0
        tight = threat.rank >= ThreatLevel.elevated.rank
        # an in-flight actuator order explains the change: weather-type corroboration would contradict it
        if "corroboration" in checks and not explained and (notable or dyn_flag or tight):
            r5, agree = self.l5.check(reading, claim)
            results += r5
        results += r6
        return await self._finish(reading, results, threat, accepted=True, prev=prev, agree=agree, notable=notable)

    async def _finish(self, reading: Reading, results: list[LayerResult], threat: ThreatLevel, *,
                      accepted: bool, prev: dict[str, Any] | None = None, agree: int = 0,
                      notable: bool = False) -> Verdict:
        sc = self.scorer.score(results, threat, agree)
        status, score, reasons = sc.status, sc.score, list(sc.reasons)
        contained = self.containment.contained_reason(reading.sensor_id) if accepted else None
        if contained:
            status = Status.untrusted
            reasons.append(contained)
            score = min(score, round(self.cfg.thresholds.scoring.cutoffs.suspect - 0.01, 4))
        v = self.engine.build(
            sensor_id=reading.sensor_id, sequence_no=reading.sequence_no, status=status, score=score,
            reasons=reasons, results=results, threat=threat, sensor_type=reading.sensor_type,
            zone_id=reading.zone_id, raw_status=sc.status, self_consistent=sc.self_consistent and accepted,
            corroborated=sc.corroborated, corroborating_sources=agree, notable=notable, value=reading.value)
        responses = self.correlator.observe_verdict(v)
        v.action_taken = self.correlator.planned_action(responses) or (
            "throttle" if "call_flood" in reasons else None)
        self.engine.publish(v, reading if accepted else None)
        await self.correlator.execute(responses)
        if accepted:
            await self.containment.on_verdict(v)
            if v.self_consistent or "rate_of_change" in v.reasons:
                await self.verifier.observe_reading(reading, prev)
        return v

    # ---------- Brain-facing verdict requests
    def request_verdict(self, sensor_id: str, sequence_no: int | None = None) -> Verdict:
        try:
            return self._request(sensor_id, sequence_no)
        except Exception as e:
            self.audit.emit("error", f"verdict request failed: {e}"[:300], sensor_id=sensor_id,
                            data={"kind": "verdict_request_error"})
            return self.engine.unknown(sensor_id, "internal_error", sequence_no)

    def _request(self, sensor_id: str, sequence_no: int | None) -> Verdict:
        s = self.state.get(sensor_id)
        if s is None:
            return self.engine.unknown(sensor_id, "unknown_sensor", sequence_no)
        threat = self.levels.get(s.zone_id)
        v = self.state.find_verdict(sensor_id, sequence_no) if sequence_no is not None else s.latest_verdict
        contained = self.containment.contained_reason(sensor_id)
        # A sensor we are actively watching and have deliberately isolated/quarantined is untrusted even if its
        # stream has briefly gone quiet: containment is a stronger, more precise signal for the Brain than "no
        # recent reading", and this keeps the verdict stable across a momentary gap at the stale boundary. A
        # sensor never heard from since a restart (last_seen is None) still falls through to the unknown fail-safe.
        if contained and v is not None and s.last_seen is not None:
            return v if v.status == Status.untrusted else self.engine.reissue(v, Status.untrusted, contained, threat)
        if self.l6.is_stale(s):
            return self.engine.unknown(sensor_id, "stale", sequence_no, s.zone_id, s.sensor_type, threat)
        if v is None:
            return self.engine.unknown(sensor_id, "no_verdict", sequence_no, s.zone_id, s.sensor_type, threat)
        is_latest = s.latest_verdict is not None and v.verdict_id == s.latest_verdict.verdict_id
        if v.expires_at <= self.clock.now() and is_latest:
            tight = self.cfg.thresholds.scoring.tightened
            weak = v.trust_score < tight.trusted_min_score or v.corroborating_sources < tight.min_corroborating_sources
            if threat.rank >= ThreatLevel.elevated.rank and v.status == Status.trusted and weak:
                return self.engine.reissue(v, Status.suspect, "threat_level_tightened", threat)
            return self.engine.reissue(v, threat=threat)
        return v
