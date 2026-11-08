"""The Actuation Gate: the only code path that can call a Twin actuator.

Rules and agents hand it a ProposedAction. It runs deterministic checks, and only a
decision it produced itself can be executed. Nothing here calls an LLM.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from brain import clock
from brain.citygraph import MemoryGraphStore
from brain.config import GatePolicy
from brain.contracts import (
    CONTRACT_VERSION,
    PARAM_MODELS,
    ActuatorCall,
    ActuatorResult,
    ProposedAction,
    VerdictStatus,
    utcnow,
)
from brain.contracts.signing import sign
from brain.departments import Manifest
from brain.ports import GuardianPort, GuardianUnavailable, TwinPort


class GateDecision(BaseModel):
    allowed: bool
    check: str  # the check that decided: "passed" or the one that failed
    reason: str = ""
    call: ActuatorCall | None = None
    idempotency_key: str | None = None
    approval_id: str | None = None  # present only when allowed; `execute` takes it exactly once
    # The facts behind the verdict, for an explanation: the checks passed so far, and the numbers the deciding check used.
    detail: dict[str, Any] = Field(default_factory=dict)


def idempotency_key(proposal: ProposedAction) -> str:
    """One pursuit unit per target, one unit per zone otherwise, one alert per zone, one recall per unit."""
    params = proposal.params
    if proposal.action == "dispatch_unit":
        mode = params.get("mode") or "respond"
        subject = params.get("target_id") if mode == "pursuit" and params.get("target_id") else params.get("zone_id")
        return f"{proposal.incident_id}|dispatch_unit|{params.get('unit_type')}|{mode}|{subject}"
    if proposal.action == "recall_unit":
        return f"{proposal.incident_id}|recall_unit|{params.get('unit_id')}"
    return f"{proposal.incident_id}|{proposal.action}|{params.get('zone_id') or proposal.actuator_id}"


class ActuationGate:
    def __init__(
        self,
        store: MemoryGraphStore,
        twin: TwinPort,
        guardian: GuardianPort,
        policy: GatePolicy,
        manifests: dict[str, Manifest],
        capabilities: set[str],
        signing_secret: str | None,
        contract_version: str = CONTRACT_VERSION,
        approvals: Any = None,
        keyring: Any = None,
    ) -> None:
        self.keyring = keyring  # signs our calls with the `brain` key (key id, EdDSA) when one is configured
        self.approvals = approvals  # an ApprovalStore when `approval.mode` is human, else None: high-impact calls are held
        self.store = store
        self.twin = twin
        self.guardian = guardian
        self.policy = policy
        self.manifests = manifests
        self.capabilities = capabilities
        self.signing_secret = signing_secret
        self.contract_version = contract_version
        self._used: set[str] = set()
        self._pending: dict[str, GateDecision] = {}
        self._per_incident: dict[str, int] = {}
        self._recent: deque[datetime] = deque()
        self._driven: dict[tuple[str, str], datetime] = {}  # (action, actuator) -> the readings' time of the last call allowed

    async def check(self, proposal: ProposedAction, now: datetime | None = None) -> GateDecision:
        now = now or utcnow()

        passed: list[str] = []

        def deny(check: str, reason: str, **facts: Any) -> GateDecision:
            return GateDecision(allowed=False, check=check, reason=reason, detail={"checks": list(passed), **facts})

        # 1. Schema
        params_model = PARAM_MODELS.get(proposal.action)
        try:
            if params_model is not None:
                params_model.model_validate(proposal.params)
            call = ActuatorCall(
                contract_version=self.contract_version,
                actuator_id=proposal.actuator_id,
                action=proposal.action,
                params=proposal.params,
                justification=proposal.justification,
                trust_ref=proposal.trust_ref,
            )
        except ValidationError as error:
            return deny("schema", f"call does not match the contract: {error.errors()[0]['msg']}")
        passed.append("schema")

        # 2. Capability: the Twin must really expose this action
        if proposal.action not in self.capabilities:
            return deny("capability", f"the Twin does not expose {proposal.action!r}", action=proposal.action)
        passed.append("capability")

        # 3. Least privilege: the action must be in the department's allowlist
        manifest = self.manifests.get(proposal.department)
        if manifest is None or not manifest.allows(proposal.action, proposal.params):
            return deny("allowlist", f"department {proposal.department} may not call {proposal.action} {proposal.params}",
                        department=proposal.department, action=proposal.action)
        passed.append("allowlist")

        # 4. A closed incident takes no new action, only the withdrawal of what is still out
        standdown = proposal.action in self.policy.standdown_actions
        incident = self.store.incident(proposal.incident_id)
        if incident is not None and incident.status == "closed" and not standdown:
            return deny("incident", f"incident {proposal.incident_id} is closed ({incident.outcome})", outcome=incident.outcome)
        passed.append("incident")

        # 5. Trust reference
        if not proposal.trust_ref:
            return deny("trust_ref", "no Guardian verdict referenced", verdict_id=None, verdict_status="missing")
        verdict = self.store.verdict(proposal.trust_ref)
        if verdict is None:
            return deny("trust_ref", f"verdict {proposal.trust_ref} is unknown to the Brain",
                        verdict_id=proposal.trust_ref, verdict_status="unknown")
        if verdict.status != VerdictStatus.TRUSTED:
            return deny("trust_ref", f"verdict {verdict.verdict_id} is {verdict.status.value}, not trusted",
                        verdict_id=verdict.verdict_id, verdict_status=verdict.status.value)
        if verdict.expires_at is not None and verdict.expires_at < now:
            return deny("trust_ref", f"verdict {verdict.verdict_id} expired at {verdict.expires_at.isoformat()}",
                        verdict_id=verdict.verdict_id, verdict_status="expired")
        if verdict.reading_ref.reading_id not in proposal.evidence_reading_ids:
            return deny("trust_ref", f"verdict {verdict.verdict_id} does not cover any cited reading",
                        verdict_id=verdict.verdict_id, verdict_status="not_covering")
        passed.append("trust_ref")

        # 6. Evidence sufficiency for this impact level
        impact = self.policy.impact.get(proposal.action, "high")
        trusted = [r for r in proposal.evidence_reading_ids if self._is_trusted(r)]
        sources = {self._witness(r) for r in trusted}
        needed = self.policy.min_trusted_sources[impact]
        direct = proposal.direct_reading_id is not None and proposal.direct_reading_id in trusted
        if len(sources) < needed and not direct:
            return deny(
                "evidence",
                f"{impact}-impact action needs {needed} independent trusted sources, found {len(sources)}{" (" + ", ".join(sorted(sources)) + ")" if sources else ""}",
                impact=impact, needed_sources=needed, witnesses=sorted(sources),
            )
        passed.append("evidence")
        human: Any = None
        if impact == "high":
            if self.approvals is None:
                return deny("human_approval", "high-impact actions need human approval, which is not wired up yet",
                            impact=impact, action=proposal.action)
            if idempotency_key(proposal) in self._used:  # already sent with an earlier approval: do not ask a person again
                return deny("idempotency", f"already issued for {idempotency_key(proposal)}")
            human, why = self.approvals.find(proposal)
            if human is None:
                pending_id = self.approvals.hold(proposal, proposal.evidence_reading_ids[-1].replace("#", ":") if proposal.evidence_reading_ids else None)
                return deny("human_approval", "a high-impact action needs a person's approval: it is waiting for one" + (f" ({why})" if why else ""),
                            impact=impact, action=proposal.action, pending_id=pending_id)
            passed.append("human_approval")

        # 7. Idempotency
        key = idempotency_key(proposal)
        if key in self._used or any(p.idempotency_key == key for p in self._pending.values()):
            return deny("idempotency", f"already issued for {key}")
        passed.append("idempotency")

        # 7b. Cooling-off: an actuator that was driven a moment ago is not driven again until the gap has passed (on the
        # readings' own clock). A stand-down is never held: it only withdraws what is out.
        gap_at = None
        min_gap = self.policy.min_gap_s.get(proposal.action, 0.0)
        if min_gap and not standdown:
            gap_at = self._event_time(proposal)
            last = self._driven.get((proposal.action, proposal.actuator_id))
            if gap_at is not None and last is not None and 0 <= (gap_at - last).total_seconds() < min_gap:
                return deny("cooling", f"{proposal.actuator_id} was last driven {(gap_at - last).total_seconds():.0f} s ago; "
                                       f"the minimum gap for {proposal.action} is {min_gap:.0f} s",
                            seconds_ago=round((gap_at - last).total_seconds(), 1), min_gap_s=min_gap)
            passed.append("cooling")

        # 8. Quarantine: never drive a device the Guardian has isolated
        try:
            if await self.guardian.is_quarantined(proposal.actuator_id):
                self.store.mark_quarantined(proposal.actuator_id)
                return deny("quarantine", f"the Guardian has quarantined {proposal.actuator_id}", actuator_id=proposal.actuator_id)
        except GuardianUnavailable as error:
            if impact != "low":
                return deny("quarantine", f"cannot confirm {proposal.actuator_id} is not quarantined: {error}", actuator_id=proposal.actuator_id)
        passed.append("quarantine")

        # 9. Actuation budget: a runaway rule or agent cannot flood the city with calls
        while self._recent and now - self._recent[0] > timedelta(seconds=60):
            self._recent.popleft()
        if not standdown:
            if self._per_incident.get(proposal.incident_id, 0) >= self.policy.max_actions_per_incident:
                limit = self.policy.max_actions_per_incident
                return deny("budget", f"incident {proposal.incident_id} reached its limit of {limit} action{'' if limit == 1 else 's'}",
                            scope="incident", used=self._per_incident.get(proposal.incident_id, 0), limit=limit)
            if len(self._recent) >= self.policy.max_actions_per_minute:
                return deny("budget", f"more than {self.policy.max_actions_per_minute} actions in the last minute",
                            scope="minute", used=len(self._recent), limit=self.policy.max_actions_per_minute)
        passed.append("budget")

        if human is not None:
            self.approvals.consume(human.approval_id)  # an approval is used once, even if the Twin then fails the call
        decision = GateDecision(
            allowed=True, check="passed", call=call, idempotency_key=key, approval_id=clock.current().new_id("approval"),
            detail={"checks": list(passed), "impact": impact, **({"human_approval_id": human.approval_id, "approver": human.approver} if human else {}), "needed_sources": needed, "witnesses": sorted(sources), "direct": direct,
                    "budget": {"incident_used": self._per_incident.get(proposal.incident_id, 0),
                               "incident_limit": self.policy.max_actions_per_incident,
                               "minute_used": len(self._recent), "minute_limit": self.policy.max_actions_per_minute}},
        )
        self._pending[decision.approval_id] = decision
        if gap_at is not None:
            self._driven[(proposal.action, proposal.actuator_id)] = gap_at
        if not standdown:
            self._per_incident[proposal.incident_id] = self._per_incident.get(proposal.incident_id, 0) + 1
            self._recent.append(now)
        return decision

    def _event_time(self, proposal: ProposedAction) -> datetime | None:
        """The newest of the readings the proposal rests on: the moment it is about, on the readings' own clock."""
        times = [r.timestamp for rid in proposal.evidence_reading_ids if (r := self.store.reading(rid)) is not None]
        return max(times, default=None)

    def snapshot(self) -> dict[str, Any]:
        """What must outlive a restart: which calls were already issued, and how much budget is spent."""
        return {"used": sorted(self._used), "per_incident": dict(self._per_incident),
                "recent": [moment.isoformat() for moment in self._recent],
                "driven": {f"{action}|{actuator}": moment.isoformat() for (action, actuator), moment in self._driven.items()}}

    def restore(self, saved: dict[str, Any]) -> None:
        self._used = set(saved.get("used", []))
        self._per_incident = {incident: int(count) for incident, count in saved.get("per_incident", {}).items()}
        self._recent = deque(datetime.fromisoformat(moment) for moment in saved.get("recent", []))
        self._driven = {tuple(key.split("|", 1)): datetime.fromisoformat(moment) for key, moment in saved.get("driven", {}).items()}

    def release(self, key: str | None) -> None:
        """A recalled unit no longer holds its place, so the same dispatch may be issued again."""
        if key:
            self._used.discard(key)

    def _witness(self, reading_id: str) -> str:
        """Who a reading counts as. By sensor, or (`independence: cause`) by type and zone: two cameras in one zone are one witness."""
        if self.policy.independence == "cause":
            reading = self.store.reading(reading_id)
            if reading is not None:
                return f"{reading.type} in {reading.zone_id}"
        return reading_id.split("#")[0]

    def _is_trusted(self, reading_id: str) -> bool:
        verdict = self.store.verdict_of(reading_id)
        return verdict is not None and verdict.status == VerdictStatus.TRUSTED

    async def execute(self, approval_id: str) -> tuple[dict[str, Any], ActuatorResult]:
        """Sign and send an approved call. Refuses anything `check` did not approve."""
        decision = self._pending.pop(approval_id, None)
        if decision is None or decision.call is None or decision.idempotency_key is None:
            raise PermissionError("only a call approved by this gate can be executed, and only once")
        self._used.add(decision.idempotency_key)

        envelope = decision.call.model_dump(mode="json", exclude={"provenance"})
        moment = clock.current()
        envelope = {**envelope, "issued_at": moment.now().isoformat().replace("+00:00", "Z"), "nonce": moment.new_id("nonce")}  # signed with the call: a copy sent later is refused
        if self.keyring is not None and self.keyring.has("brain"):
            envelope = self.keyring.sign("brain", envelope, signed_by="city_brain")
        elif self.signing_secret:
            envelope = sign(envelope, self.signing_secret, signed_by="city_brain")
        call = ActuatorCall.model_validate(envelope)
        try:
            result = await self.twin.call_actuator(call)
        except Exception:
            # The Twin was not reached (or its answer was lost), so the key goes back: the same dispatch may be tried again,
            # and a Twin that did act answers `duplicate`. The action budget stays spent, so retries are bounded.
            if self.policy.retry_unreached:
                self._used.discard(decision.idempotency_key)
            raise
        return envelope, result
