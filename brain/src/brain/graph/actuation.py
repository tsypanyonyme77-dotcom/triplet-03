"""Shared by the reflex graph and the department teams: turning an intention into a
ProposedAction, passing proposals through the gate, executing what it approves, and
standing units down again."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from brain.citygraph import MemoryGraphStore
from brain.contracts import Incident, ProposedAction, VerdictStatus
from brain.departments import Manifest, Rule, matches, render
from brain.gate import ActuationGate, idempotency_key
from brain.timeline import Timeline


@dataclass
class Actuation:
    store: MemoryGraphStore
    gate: ActuationGate
    timeline: Timeline
    manifest: Manifest
    config_hash: str
    rules: list[Rule] = field(default_factory=list)
    # Every department by code, for rules and proposals that belong to a department other than `manifest`.
    manifests: dict[str, Manifest] = field(default_factory=dict)
    # (incident, suspect) -> the perimeter in force: where it was planned from and the zones it expects them in.
    plans: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    decisions: int = 0
    # Chooses the station for a dispatch when set (`optimiser.dispatch: on`); None keeps nearest-first.
    chooser: Any = None
    # Called after the Twin confirms a dispatch (the emergency corridor); None when `orchestration.planner` is off.
    on_dispatch: Any = None
    # Plans an overload's disconnections across a feeder when `optimiser.shed` is on; None keeps the plain rule.
    shedder: Any = None
    # The corridors opened so far (a compact record of each), for the Traffic control desk's brief.
    corridors: list[dict[str, Any]] = field(default_factory=list)

    def next_decision_id(self) -> str:
        self.decisions += 1
        return f"dec-{self.decisions:04d}"


def trust_ref_for(store: MemoryGraphStore, incident: Incident) -> str | None:
    """The verdict on the first trusted piece of evidence that the incident happened."""
    for reading_id in incident.evidence:
        verdict = store.verdict_of(reading_id)
        if verdict and verdict.status == VerdictStatus.TRUSTED:
            return verdict.verdict_id
    return None


# Where each kind of unit is based. A unit type not listed here falls back to the department's own facility.
UNIT_FACILITY = {"police": "police_station", "fire": "fire_station", "ambulance": "hospital"}


def _station(act: Actuation, zone_id: str, reserved: dict[str, int], kind: str, incident: Incident | None = None) -> dict[str, Any] | None:
    if act.chooser is not None and incident is not None:
        return act.chooser.choose(act, incident, zone_id, reserved, kind)
    return act.store.nearest_facility(zone_id, kind, need_unit=True, reserved=reserved)


def _station_kind(params: dict[str, Any], manifest: Manifest) -> str:
    return UNIT_FACILITY.get(params.get("unit_type", "")) or manifest.facility_type or ""


def make_proposal(
    act: Actuation,
    incident: Incident,
    evidence_reading_ids: list[str],
    action: str,
    params: dict[str, Any],
    *,
    tier: str,
    justification: str,
    rule_id: str | None = None,
    knowledge_citations: list[str] | None = None,
    reserved: dict[str, int] | None = None,
    direct_reading_id: str | None = None,
    actuator_id: str | None = None,
    trust_ref: str | None = None,
    manifest: Manifest | None = None,
) -> ProposedAction | None:
    """Build a proposal, choosing the station a dispatch should come from.

    `manifest` names the department the proposal belongs to; it defaults to the acting department.

    `reserved` counts units already promised to earlier proposals in the same plan.
    `trust_ref` defaults to the verdict on the evidence that the incident happened.
    Returns None when the action needs a unit and no station has one.
    """
    reserved = reserved if reserved is not None else {}
    manifest = manifest or act.manifest
    if actuator_id is None and action == "dispatch_unit":
        station = _station(act, params.get("zone_id", incident.zone_id), reserved, _station_kind(params, manifest), incident)
        if station is None:
            return None
        reserved[station["id"]] = reserved.get(station["id"], 0) + 1
        actuator_id = station.get("actuator_id") or f"{manifest.code.lower()}-dispatch"
    elif actuator_id is None:
        actuator_id = f"{action.replace('_', '-')}-{params.get('zone_id', incident.zone_id)}"

    trust_ref = trust_ref or trust_ref_for(act.store, incident)
    knowledge = list(dict.fromkeys([*(knowledge_citations or []), *([rule_id] if rule_id else [])]))
    return ProposedAction(
        department=manifest.code,
        tier=tier,
        incident_id=incident.incident_id,
        action=action,
        actuator_id=actuator_id,
        params=params,
        justification=justification[:500],
        trust_ref=trust_ref,
        evidence_reading_ids=evidence_reading_ids,
        direct_reading_id=direct_reading_id,
        citations=[*evidence_reading_ids, *([trust_ref] if trust_ref else []), *knowledge],
        knowledge_citations=knowledge,
        rule_id=rule_id,
    )


async def gate_proposals(
    act: Actuation, proposals: list[dict[str, Any]], already_blocked: list[str], trace_id: str | None
) -> tuple[list[dict[str, Any]], list[str]]:
    """Returns (approvals to execute, dedupe keys of the blocks reported this time)."""
    approvals: list[dict[str, Any]] = []
    new_blocked: list[str] = []
    for dumped in proposals:
        proposal = ProposedAction.model_validate(dumped)
        decision = await act.gate.check(proposal)

        # A quarantined station is not the end of the road: try the next nearest one.
        while not decision.allowed and decision.check == "quarantine" and proposal.action == "dispatch_unit":
            _report_block(act, proposal, decision.check, decision.reason, already_blocked, new_blocked, trace_id, decision.detail)
            manifest = act.manifests.get(proposal.department, act.manifest)
            station = _station(act, proposal.params.get("zone_id", ""), {}, _station_kind(proposal.params, manifest))
            if station is None or station.get("actuator_id") == proposal.actuator_id:
                break
            proposal = proposal.model_copy(update={"actuator_id": station["actuator_id"]})
            decision = await act.gate.check(proposal)

        if decision.check in ("idempotency", "quarantine"):
            continue
        if not decision.allowed:
            _report_block(act, proposal, decision.check, decision.reason, already_blocked, new_blocked, trace_id, decision.detail)
            continue

        decision_id = act.next_decision_id()
        act.store.add_decision(decision_id, proposal, act.config_hash)
        act.timeline.emit(
            "brain.decision.made", proposal.incident_id,
            {"decision_id": decision_id, "department": proposal.department, "tier": proposal.tier,
             "action": proposal.action, "actuator_id": proposal.actuator_id, "params": proposal.params,
             "justification": proposal.justification, "citations": proposal.citations,
             "trust_ref": proposal.trust_ref, "config_hash": act.config_hash,
             "evidence": proposal.evidence_reading_ids, "direct_reading": proposal.direct_reading_id,
             "rule_id": proposal.rule_id, "knowledge": proposal.knowledge_citations, "gate": decision.detail},
            trace_id,
        )
        approvals.append({
            "decision_id": decision_id, "approval_id": decision.approval_id,
            "proposal": proposal.model_dump(mode="json"),
        })
    return approvals, new_blocked


def _report_block(
    act: Actuation, proposal: ProposedAction, check: str, reason: str,
    already_blocked: list[str], new_blocked: list[str], trace_id: str | None, detail: dict[str, Any] | None = None,
) -> None:
    subject = proposal.params.get("target_id") or proposal.params.get("zone_id")
    key = f"gate|{check}|{proposal.action}|{proposal.params.get('mode')}|{subject}|{proposal.actuator_id}"
    if key in already_blocked or key in new_blocked:
        return
    new_blocked.append(key)
    act.timeline.emit(
        "brain.action.blocked", proposal.incident_id,
        {"stage": "gate", "check": check, "reason": reason, "would_have": proposal.action,
         "actuator_id": proposal.actuator_id, "params": proposal.params, "gate": detail or {},
         "evidence": proposal.evidence_reading_ids, "trust_ref": proposal.trust_ref},
        trace_id,
    )


async def execute_approvals(
    act: Actuation, approvals: list[dict[str, Any]], trace_id: str | None
) -> list[dict[str, Any]]:
    """Send each approved call. Returns one record per call: decision, proposal and result."""
    actions = []
    for approval in approvals:
        proposal, decision_id = approval["proposal"], approval["decision_id"]
        act.timeline.emit(
            "brain.action.requested", proposal["incident_id"],
            {"decision_id": decision_id, "actuator_id": proposal["actuator_id"], "action": proposal["action"],
             "params": proposal["params"], "trust_ref": proposal["trust_ref"]},
            trace_id,
        )
        try:
            call, result = await act.gate.execute(approval["approval_id"])
            outcome = result.model_dump(mode="json", exclude_none=True)
        except Exception as error:  # a Twin that is down or rejects the call must not crash the Brain  # noqa: BLE001
            call, outcome = {}, {"status": "error", "reason": f"{type(error).__name__}: {error}"}
        action, params, status, unit_id = proposal["action"], proposal["params"], outcome.get("status"), outcome.get("unit_id")
        released = None
        # `duplicate` is the Twin saying it already holds this dispatch: after a restart that is how
        # the Brain learns which unit it sent, so it goes on the books like a fresh one.
        if action == "dispatch_unit" and unit_id and status in ("dispatched", "duplicate"):
            act.store.commit_unit(
                proposal["actuator_id"], str(unit_id), incident_id=proposal["incident_id"],
                mode=params.get("mode") or "respond", zone_id=params.get("zone_id"), target_id=params.get("target_id"),
                key=idempotency_key(ProposedAction.model_validate(proposal)),
            )
        elif action == "dispatch_unit" and status == "dispatched":
            act.store.commit_unit(proposal["actuator_id"])
        elif action == "recall_unit" and status in ("recalled", "duplicate"):
            released = _write_off(act, {"unit_id": params.get("unit_id")})
        action_id = str(unit_id) if action == "dispatch_unit" and unit_id else f"{decision_id}-action"
        act.store.add_action(decision_id, action_id, call, outcome)
        act.timeline.emit("brain.action.result", proposal["incident_id"], {"decision_id": decision_id, **outcome}, trace_id)
        if action == "dispatch_unit" and act.on_dispatch is not None:
            await act.on_dispatch(proposal, outcome, trace_id)
        actions.append({
            "decision_id": decision_id, "action": action, "actuator_id": proposal["actuator_id"],
            "params": params, "result": outcome, **({"released": released} if released else {}),
        })
    return actions


def _write_off(act: Actuation, unit: dict[str, Any]) -> dict[str, Any] | None:
    """Take a unit off the Brain's books and free its place at the gate."""
    released = act.store.release_unit(unit["unit_id"])
    if released is not None:
        act.gate.release(released.get("key"))
    return released


async def stand_down(
    act: Actuation,
    incident: Incident,
    units: list[dict[str, Any]],
    *,
    scope: str,
    reading_id: str,
    cause: str,
    trace_id: str | None,
    already_blocked: list[str] | None = None,
    returned: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Recall units through the gate and report which are free again.

    `scope` picks the department's rules (`closed` or `departed`); `reading_id` is the trusted
    reading that justifies standing down. `returned` are units that ended their own task
    and need no call. A unit no rule covers, or that the Twin offers no recall for, is only
    taken off the Brain's books. Returns the dedupe keys of any blocks reported.
    """
    verdict = act.store.verdict_of(reading_id)
    trust_ref = verdict.verdict_id if verdict is not None and verdict.status == VerdictStatus.TRUSTED else None
    proposals, uncovered = [], []
    for unit in units:
        context = {"incident": incident.model_dump(mode="json"), "unit": unit}
        rule = next((r for r in act.rules if r.scope == scope and matches(r, context)), None)
        template = next((t for t in rule.do if t.action in act.gate.capabilities), None) if rule else None
        if rule is None or template is None or trust_ref is None:
            uncovered.append(unit)
            continue
        proposal = make_proposal(
            act, incident, [reading_id], template.action, render(template, context), tier="reflex",
            justification=f"{cause}. Standing down {unit['unit_id']} ({unit.get('mode')}, {unit.get('zone_id')}). Rule {rule.id}.",
            rule_id=rule.id, actuator_id=unit["actuator_id"], trust_ref=trust_ref,
        )
        proposals.append(proposal.model_dump(mode="json"))

    approvals, new_blocked = await gate_proposals(act, proposals, already_blocked or [], trace_id)
    actions = await execute_approvals(act, approvals, trace_id)
    freed = [{**a["released"], "recalled": True} for a in actions if a.get("released")]
    for unit in [*uncovered, *(returned or [])]:
        if (released := _write_off(act, unit)) is not None:
            freed.append({**released, "recalled": False})
    if freed:
        act.timeline.emit(
            "brain.units.released", incident.incident_id,
            {"cause": cause, "units": [
                {key: unit.get(key) for key in ("unit_id", "mode", "zone_id", "actuator_id", "recalled")} for unit in freed
            ]},
            trace_id,
        )
    return new_blocked


async def preempt_for(act: Actuation, asking: Incident, zone_id: str, evidence_reading_ids: list[str], trace_id: str | None) -> bool:
    """Free one unit for a named suspect's pursuit by recalling a perimeter unit of another incident. True if one was freed.

    Only a unit that holds a perimeter (never a pursuit unit), only from an incident that still has its own pursuit unit
    out, never from the incident that is asking, and the one whose station is nearest to where the unit is needed. The
    recall goes through the gate like any other, on a trusted reading of the asking incident. A unit is never written
    off the books unless the recall really went out.
    """
    rule = next((r for r in act.rules if r.scope == "preempted"), None)
    trusted = next((r for r in evidence_reading_ids if (v := act.store.verdict_of(r)) is not None and v.status == VerdictStatus.TRUSTED), None)
    if rule is None or trusted is None or "recall_unit" not in act.gate.capabilities:
        return False
    stations = {f["actuator_id"]: f for f in act.store.facilities() if not f["quarantined"]}
    candidates = []
    for unit in act.store.units_out(mode="contain"):
        owner = act.store.incident(unit.get("incident_id") or "")
        station = stations.get(unit.get("actuator_id"))
        if owner is None or owner.status != "open" or owner.incident_id == asking.incident_id or station is None:
            continue
        if not act.store.units_out(owner.incident_id, "pursuit"):
            continue  # that incident has nothing but this unit left on the street
        distance = act.store.hop_distance(zone_id, station["zone_id"])
        candidates.append((99 if distance is None else distance, unit["unit_id"], unit, owner))
    if not candidates:
        return False
    _, _, unit, owner = min(candidates, key=lambda c: (c[0], c[1]))
    await stand_down(
        act, owner, [unit], scope="preempted", reading_id=trusted, trace_id=trace_id,
        cause=f"Preempted: a named suspect in {asking.incident_id} has no unit and the stations are empty, "
              f"so one perimeter unit of {owner.incident_id} is sent there instead",
    )
    return not any(u["unit_id"] == unit["unit_id"] for u in act.store.units_out())
