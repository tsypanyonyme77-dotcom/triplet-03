"""Call auditor: every Brain actuator call passes authorisation (trust_ref), policy and safety invariants,
rate limits and capability checks before it is forwarded to the Twin. Every call is audited."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta

from pydantic import ValidationError

from guardian.actuator_watch.effect_verifier import EffectVerifier
from guardian.adapters.schemas import ActuatorCallIn, TwinReply
from guardian.adapters.twin_client import TwinClient, TwinUnavailable
from guardian.audit.logger import AuditLogger
from guardian.clock import Clock
from guardian.config import CityModel, Crosschecks, Policies
from guardian.containment.manager import ContainmentManager
from guardian.detectors.semantic_plausibility import SemanticDetector
from guardian.ingest.state_store import StateStore
from guardian.models import ActuatorCall, Decision, Status
from guardian.threat.correlator import Correlator


class CallAuditor:
    def __init__(self, policies: Policies, city: CityModel, cc: Crosschecks, state: StateStore,
                 containment: ContainmentManager, semantic: SemanticDetector, twin: TwinClient,
                 verifier: EffectVerifier, correlator: Correlator, audit: AuditLogger, clock: Clock) -> None:
        self.p, self.city, self.cc, self.state = policies, city, cc, state
        self.containment, self.semantic, self.twin = containment, semantic, twin
        self.verifier, self.correlator, self.audit, self.clock = verifier, correlator, audit, clock
        self.calls: deque[tuple[datetime, str, str]] = deque(maxlen=10_000)  # ts, caller, actuator
        self.dispatched: set[str] = set(state.db.get_kv("dispatched_incidents", []))

    def _authorise(self, call: ActuatorCall, zone: str | None) -> list[str]:
        if not call.trust_ref:
            return ["trust_ref_missing"]
        v = self.state.get_verdict(call.trust_ref)
        if v is None:
            return ["trust_ref_unknown"]
        out = []
        if v.status != Status.trusted:
            out.append("trust_ref_not_trusted")
        if v.expires_at < self.clock.now():
            out.append("trust_ref_expired")
        reason = self.containment.contained_reason(v.sensor_id)
        if reason:
            out.append(reason)
        if zone and v.zone_id and v.zone_id != zone and v.zone_id not in self.cc.adjacency.get(zone, []):
            out.append("trust_ref_zone_mismatch")
        return out

    def _policy(self, call: ActuatorCall, zone: str | None, caller: str) -> list[str]:
        out = []
        z = self.city.zones.get(zone or "")
        if (call.action == "set_grid_state" and call.params.get("state") == "disconnected" and z and z.hospital
                and self.p.safety.no_grid_disconnect_in_hospital_zone):
            out.append("safety_hospital_grid")
        if call.action == "dispatch_unit" and self.p.safety.no_duplicate_dispatch:
            if not call.incident_id:
                out.append("incident_id_missing")
            elif call.incident_id in self.dispatched:
                out.append("duplicate_dispatch")
        cap = self.semantic.action_capability(call, zone)
        if cap:
            out.append(cap)
        now = self.clock.now()
        minute = now - timedelta(seconds=60)
        by_caller = sum(1 for t, c, _ in self.calls if c == caller and t > minute)
        by_act = sum(1 for t, _, a in self.calls if a == call.actuator_id and t > minute)
        if by_caller >= self.p.rate_limits.per_caller_per_min or by_act >= self.p.rate_limits.per_actuator_per_min:
            out.append("rate_limited")
        return out

    async def handle(self, call: ActuatorCall, caller: str) -> Decision:
        now = self.clock.now()
        actuator = self.p.actuators.get(call.actuator_id)
        zone = (actuator.zone_id if actuator else None) or call.zone_id
        reasons: list[str] = []
        warnings: list[str] = []
        if self.containment.is_quarantined(caller):
            reasons.append("caller_quarantined")
        if call.action in self.p.containment_actions:
            reasons.append("containment_reserved")  # only the Guardian itself issues containment
        if actuator is None:
            reasons.append("unknown_actuator")
        reasons += self._authorise(call, zone)
        if self.containment.is_quarantined(call.actuator_id):
            reasons.append("device_quarantined")
        if self.containment.is_unreliable(call.actuator_id):
            reasons.append("actuator_unreliable")
        reasons += self._policy(call, zone, caller)
        hour = (now + timedelta(hours=self.city.timezone_offset_h)).hour
        if hour in self.p.odd_hours.hours and call.action in self.p.odd_hours.actions:
            warnings.append("odd_hour_action")
        self.calls.append((now, caller, call.actuator_id))
        reasons = list(dict.fromkeys(reasons))

        reply: dict[str, object] | None = None
        if not reasons:
            try:
                raw = await self.twin.call_tool(call.action, ActuatorCallIn.from_call(call).model_dump())
                reply = TwinReply.model_validate(raw).model_dump()
            except (TwinUnavailable, ValidationError) as e:
                reasons.append("twin_unreachable")
                self.audit.emit("error", f"twin call {call.call_id} failed: {e}"[:300], actuator_id=call.actuator_id,
                                zone_id=zone, data={"kind": "twin_unreachable"})
        if reply is not None:
            if reply.get("status") == "rejected":
                warnings.append("twin_rejected")
            else:
                if call.action == "dispatch_unit" and call.incident_id:
                    self.dispatched.add(call.incident_id)
                    self.state.db.put_kv("dispatched_incidents", sorted(self.dispatched))
                warnings += await self.verifier.expect(call, reply)
        decision = Decision(call_id=call.call_id, decision="blocked" if reply is None else "forwarded",
                            reasons=reasons + warnings, twin_reply=reply)
        self.audit.emit(
            "decision", f"{decision.decision} {call.action} {call.actuator_id}"
                        + (f" ({', '.join(decision.reasons)})" if decision.reasons else ""),
            actuator_id=call.actuator_id, zone_id=zone,
            data={"kind": "actuator_call", "caller": caller, "call": call.model_dump(),
                  "justification": call.justification, "decision": decision.decision,
                  "reasons": decision.reasons, "twin_reply": reply})
        responses = self.correlator.observe_decision(caller, call.actuator_id, zone, decision.reasons, call.call_id)
        await self.correlator.execute(responses)
        return decision
