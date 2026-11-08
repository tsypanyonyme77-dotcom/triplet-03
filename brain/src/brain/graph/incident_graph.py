"""The reflex graph: one LangGraph thread per incident, no LLM anywhere on this path.

    enrich -> reflex -> gate -> actuate

Each new piece of evidence re-invokes the same thread (`thread_id = incident_id`), so the
checkpointed state remembers what has already been decided for this incident. When a case
needs judgement, the reflex tier asks the department team to deliberate in the background
and carries on.

Incidents that are not crimes (flood, jam, fire, accident) take a shorter way through `reflex`:
`condition` rules propose and the same gate disposes (see `condition.py`).

Rules react to three things here: one person's assessment (pursue them), the scene as a
whole (send a unit when several people fled and no one stands out), and a suspect seen
outside the perimeter built for them (stand it down and ask for a new plan).
"""

from __future__ import annotations

import operator
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated, Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from brain.config import Policy
from brain.contracts import Assessment, Incident, VerdictStatus
from brain.departments import Rule, matches, render
from brain.departments.police import assess
from brain.graph.actuation import Actuation, execute_approvals, gate_proposals, make_proposal, preempt_for, stand_down
from brain.graph.condition import condition_proposals
from brain.tools import geo


def _merge(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    return {**left, **right}


class IncidentState(TypedDict, total=False):
    # Input for this run
    incident_id: str
    trace_id: str
    # Recomputed on every run
    candidates: list[str]
    assessments: list[dict[str, Any]]
    proposals: list[dict[str, Any]]
    approvals: list[dict[str, Any]]
    replan: list[str]  # suspects whose perimeter was just stood down
    # Remembered across runs of the same incident
    levels: Annotated[dict[str, str], _merge]  # entity -> last reported level
    scores: Annotated[dict[str, float], _merge]  # entity -> last reported score
    pursued: Annotated[dict[str, str], _merge]  # entity -> zone last reported
    planned: Annotated[dict[str, str], _merge]  # entity -> the learned plan applied for them (the team is not asked)
    blocked: Annotated[list[str], operator.add]  # dedupe keys of blocked events
    actions: Annotated[list[dict[str, Any]], operator.add]


# (incident_id, entity_id, reason, assessment, trace_id)
RequestDeliberation = Callable[[str, str, str, dict[str, Any], str | None], None]


@dataclass
class Deps:
    actuation: Actuation
    policy: Policy
    rules: list[Rule]
    incidents: dict[str, Incident]
    request_deliberation: RequestDeliberation | None = None
    doubted: Callable[[str], bool] | None = None  # is this reading's value doubted by the forward models?


def reflex_justification(assessment: Assessment, rule_id: str) -> str:
    parts = [f"{f.name} ({', '.join(f.reading_ids) or 'history'})" for f in assessment.features]
    return f"Suspect {assessment.entity_id} score {assessment.score:.2f}: {'; '.join(parts)}. Rule {rule_id}."


def _fled(assessment: Assessment) -> str | None:
    """The trusted reading that shows this person, seen at the scene, leaving it fast. None if there is none."""
    names = {f.name: f for f in assessment.features}
    flight = names.get("flight")
    return flight.reading_ids[0] if "copresence" in names and flight and flight.trust >= 1.0 else None


def build_incident_graph(deps: Deps):
    act, scoring = deps.actuation, deps.policy.scoring
    store, timeline = act.store, act.timeline

    def learned_plan(incident: Incident, assessment: Assessment, trace_id: str | None) -> list[dict[str, Any]]:
        """The first learned plan that fits this suspect, as proposals, only if every part of it can be proposed.

        Asked at the moment the team would be: right after the pursuit went out, when the units that are really free
        (and the stations the Guardian has quarantined) are known. A compiled plan is a cache of what the team decided;
        when it cannot be made whole, none of it is used and the team is asked as usual.
        """
        context = {"incident": incident.model_dump(mode="json"), "assessment": assessment.model_dump(mode="json")}
        for rule in deps.rules:
            if rule.scope != "plan" or not matches(rule, context):
                continue
            # The team never commits units it must keep in reserve, so neither does a plan compiled from it.
            spare = (sum(f["available"] for f in store.facilities(act.manifest.facility_type) if not f["quarantined"])
                     - deps.policy.tactics.reserve_units)
            if sum(1 for t in rule.do if t.action == "dispatch_unit") > spare:
                continue
            trial: dict[str, int] = {}  # units this plan has promised so far, so two parts of it do not take the same one
            made = []
            for template in rule.do:
                proposal = make_proposal(
                    act, incident, assessment.evidence_reading_ids, template.action, render(template, context), tier="reflex",
                    justification=f"Learned plan {rule.id} for this pattern, made by the team {(rule.learned or {}).get('support', 'before')} times. "
                                  f"Suspect {assessment.entity_id}. Rule {rule.id}.",
                    rule_id=rule.id, reserved=trial, direct_reading_id=assessment.direct_reading_id,
                )
                if proposal is None:
                    made = []
                    break
                made.append(proposal)
            if made:
                timeline.emit("brain.plan.compiled", incident.incident_id, {
                    "rule_id": rule.id, "entity_id": assessment.entity_id,
                    "actions": [{"action": p.action, "params": {k: v for k, v in p.params.items() if k != "target_id"}} for p in made],
                }, trace_id)
                return [p.model_dump(mode="json") for p in made]
        return []

    def deliberate(incident_id: str, assessment: Assessment, reason: str, trace_id: str | None) -> None:
        if deps.request_deliberation is not None:
            deps.request_deliberation(incident_id, assessment.entity_id, reason, assessment.model_dump(mode="json"), trace_id)

    async def enrich(state: IncidentState) -> dict[str, Any]:
        incident = deps.incidents[state["incident_id"]]
        if incident.type != "crime":
            return {"candidates": []}
        zones = store.zones_within(incident.zone_id, scoring.flight_radius_hops)
        start = incident.occurred_at - timedelta(seconds=scoring.copresence_window_s.before)
        end = incident.occurred_at + timedelta(seconds=scoring.flight_window_s)
        return {"candidates": store.entities_seen(zones, start, end)}

    async def reflex(state: IncidentState) -> dict[str, Any]:
        incident = deps.incidents[state["incident_id"]]
        trace_id = state.get("trace_id")
        if incident.type != "crime":
            proposals, new_blocked = await condition_proposals(act, deps.rules, incident, state.get("blocked", []), trace_id, deps.doubted)
            return {"assessments": [], "proposals": proposals, "replan": [], "levels": {}, "scores": {}, "pursued": {},
                    "blocked": new_blocked}
        levels, pursued, blocked = state.get("levels", {}), state.get("pursued", {}), state.get("blocked", [])
        scores = state.get("scores", {})
        new_levels, new_scores, new_pursued, new_blocked = {}, {}, {}, []
        assessments, proposals, replan = [], [], []
        reserved: dict[str, int] = {}
        fled: dict[str, str] = {}  # person at the scene -> the trusted reading of their flight
        singled_out = len(pursued)

        for entity_id in state["candidates"]:
            assessment = assess(incident, entity_id, store, scoring)
            assessments.append(assessment.model_dump(mode="json"))
            if (flight_reading := _fled(assessment)) is not None:
                fled[entity_id] = flight_reading

            if entity_id in pursued:
                if assessment.last_zone_id and assessment.last_zone_id != pursued[entity_id]:
                    new_pursued[entity_id] = assessment.last_zone_id
                    timeline.emit(
                        "brain.suspect.tracked", incident.incident_id,
                        {"entity_id": entity_id, "zone_id": assessment.last_zone_id}, trace_id,
                    )
                if await outrun(incident, entity_id, blocked + new_blocked, new_blocked, trace_id):
                    replan.append(entity_id)
                continue

            if assessment.level == "suspect":
                singled_out += 1
            # Reported when the level changes, and when the picture of someone already being watched shifts.
            shifted = assessment.level != "none" and abs(assessment.score - scores.get(entity_id, assessment.score)) >= 0.05
            if assessment.level != levels.get(entity_id, "none") or shifted:
                new_levels[entity_id], new_scores[entity_id] = assessment.level, assessment.score
                timeline.emit(
                    "brain.suspect.assessed", incident.incident_id,
                    {
                        "entity_id": entity_id, "level": assessment.level, "score": assessment.score,
                        "zone_id": assessment.last_zone_id,
                        "features": [{"name": f.name, "trust": f.trust, "readings": f.reading_ids, "note": f.note} for f in assessment.features],
                        "trusted_sources": assessment.trusted_sources,
                        **({"fled_with": assessment.fled_with} if assessment.fled_with else {}),
                        **({"unaccounted": assessment.unaccounted} if assessment.unaccounted else {}),
                    },
                    trace_id,
                )
            if assessment.level == "poi":
                # Asked on every run; the team only takes the case again when the evidence has grown.
                deliberate(incident.incident_id, assessment, "ambiguous", trace_id)

            context ={"incident": incident.model_dump(mode="json"), "assessment": assessment.model_dump(mode="json")}
            fired = False
            for rule in deps.rules:
                if rule.scope != "assessment" or not matches(rule, context):
                    continue
                fired = True
                for template in rule.do:
                    params = render(template, context)

                    def build(params=params, template=template, rule=rule):
                        return make_proposal(
                            act, incident, assessment.evidence_reading_ids, template.action, params,
                            tier="reflex", justification=reflex_justification(assessment, rule.id), rule_id=rule.id,
                            reserved=reserved, direct_reading_id=assessment.direct_reading_id,
                        )

                    proposal = build()
                    if proposal is None and template.action == "dispatch_unit" and deps.policy.tactics.preempt_perimeter:
                        # No station has a unit: take a perimeter unit from another incident that still has its pursuit out.
                        if await preempt_for(act, incident, params.get("zone_id", incident.zone_id), assessment.evidence_reading_ids, trace_id):
                            proposal = build()
                    if proposal is not None:
                        proposals.append(proposal.model_dump(mode="json"))
                    elif (key := f"resources|{entity_id}") not in blocked:
                        new_blocked.append(key)
                        timeline.emit(
                            "brain.action.blocked", incident.incident_id,
                            {"stage": "reflex", "check": "resources", "would_have": template.action,
                             "entity_id": entity_id, "reason": "no station has a unit available"},
                            trace_id,
                        )

            # The data alone would have triggered a pursuit, but we do not believe enough of it.
            key = f"withheld|{entity_id}"
            if not fired and assessment.raw_score >= scoring.suspect_threshold and assessment.discounted and key not in blocked:
                new_blocked.append(key)
                timeline.emit(
                    "brain.action.blocked", incident.incident_id,
                    {
                        "stage": "reflex", "check": "trust", "would_have": "dispatch_unit", "entity_id": entity_id,
                        "reason": f"raw score {assessment.raw_score:.2f} would trigger a pursuit, but the trust-weighted score is {assessment.score:.2f}",
                        "discounted_evidence": assessment.discounted,
                    },
                    trace_id,
                )

        # The scene as a whole: what to do about the incident when no one person stands out.
        responded = any(a["params"].get("mode") == "respond" for a in state.get("actions", []))
        context = {"incident": incident.model_dump(mode="json"), "scene": {"fled": len(fled), "singled_out": singled_out}}
        for rule in deps.rules:
            if responded or rule.scope != "scene" or not matches(rule, context):
                continue
            evidence = list(dict.fromkeys([*incident.evidence, *fled.values()]))
            for template in rule.do:
                proposal = make_proposal(
                    act, incident, evidence, template.action, render(template, context), tier="reflex",
                    justification=(
                        f"{incident.type.capitalize()} reported in {incident.zone_id} ({', '.join(incident.evidence)}); "
                        f"{len(fled)} people left the scene fast, so flight singles no one out. Rule {rule.id}."
                    ),
                    rule_id=rule.id, reserved=reserved,
                )
                if proposal is not None:
                    proposals.append(proposal.model_dump(mode="json"))
                elif "resources|scene" not in blocked and "resources|scene" not in new_blocked:
                    new_blocked.append("resources|scene")
                    timeline.emit(
                        "brain.action.blocked", incident.incident_id,
                        {"stage": "reflex", "check": "resources", "would_have": template.action,
                         "reason": "no station has a unit available"},
                        trace_id,
                    )

        return {"assessments": assessments, "proposals": proposals, "replan": replan,
                "levels": new_levels, "scores": new_scores, "pursued": new_pursued, "blocked": new_blocked}

    async def outrun(incident: Incident, entity_id: str, blocked: list[str], new_blocked: list[str], trace_id: str | None) -> bool:
        """If a trusted sighting puts a pursued suspect outside their perimeter, stand it down. Returns whether it did."""
        plan = act.plans.get((incident.incident_id, entity_id))
        sightings = store.sightings(entity_id)
        if plan is None or not sightings or sightings[-1].zone_id in plan["inside"]:
            return False
        last = sightings[-1]
        verdict = store.verdict_of(last.reading_id)
        if verdict is None or verdict.status != VerdictStatus.TRUSTED:
            return False  # an unvouched sighting cannot dissolve a perimeter
        del act.plans[(incident.incident_id, entity_id)]
        timeline.emit(
            "brain.plan.outdated", incident.incident_id,
            {"entity_id": entity_id, "zone_id": last.zone_id, "reading_id": last.reading_id,
             "option": plan["option"], "held_zones": plan["contain_zones"]},
            trace_id,
        )
        units = [u for u in store.units_out(incident.incident_id, "contain") if u.get("target_id") == entity_id]
        new_blocked.extend(await stand_down(
            act, incident, units, scope="departed", reading_id=last.reading_id,
            cause=f"{entity_id} was seen in {last.zone_id}, outside the perimeter ({', '.join(plan['contain_zones'])})",
            trace_id=trace_id, already_blocked=blocked,
        ))
        return True

    async def gate(state: IncidentState) -> dict[str, Any]:
        approvals, new_blocked = await gate_proposals(act, state["proposals"], state.get("blocked", []), state.get("trace_id"))
        return {"approvals": approvals, "blocked": new_blocked}

    async def actuate(state: IncidentState) -> dict[str, Any]:
        trace_id, incident = state.get("trace_id"), deps.incidents[state["incident_id"]]
        actions = await execute_approvals(act, state["approvals"], trace_id)
        pursued, planned, new_blocked = {}, {}, []
        for action in list(actions):
            target = action["params"].get("target_id")
            if target and action["params"].get("mode") == "pursuit" and action["result"].get("status") in ("dispatched", "duplicate"):
                pursued[target] = action["params"].get("zone_id", "")
                # The pursuit is under way; let the department work out how to close the net.
                dumped = next((a for a in state["assessments"] if a["entity_id"] == target), None)
                if dumped is None:
                    continue
                assessment = Assessment.model_validate(dumped)
                if made := learned_plan(incident, assessment, trace_id):
                    # A plan sleep compiled for exactly this pattern goes out in place of a team run.
                    approvals, blocked = await gate_proposals(act, made, state.get("blocked", []), trace_id)
                    sent = await execute_approvals(act, approvals, trace_id)
                    actions += sent
                    new_blocked += blocked
                    planned[target] = made[0]["rule_id"]
                    held = [a["params"]["zone_id"] for a in sent if a["params"].get("mode") == "contain"
                            and a["result"].get("status") in ("dispatched", "duplicate")]
                    if held and assessment.last_zone_id:
                        # The same perimeter in force as the team's would be, so an outrun suspect is still noticed.
                        act.plans[(incident.incident_id, target)] = {
                            "option": "learned", "zone": assessment.last_zone_id, "contain_zones": held,
                            "inside": sorted(geo.expected_zones(store, assessment.last_zone_id, held)),
                        }
                else:
                    deliberate(state["incident_id"], assessment, "plan", trace_id)
        # The old perimeter is back at its stations by now, so the department can plan with those units.
        for entity_id in state.get("replan", []):
            dumped = next((a for a in state["assessments"] if a["entity_id"] == entity_id), None)
            if dumped is not None:
                deliberate(state["incident_id"], Assessment.model_validate(dumped), "replan", trace_id)
        return {"actions": actions, "pursued": pursued, "planned": planned, "blocked": new_blocked}

    graph = StateGraph(IncidentState)
    graph.add_node("enrich", enrich)
    graph.add_node("reflex", reflex)
    graph.add_node("gate", gate)
    graph.add_node("actuate", actuate)
    graph.add_edge(START, "enrich")
    graph.add_edge("enrich", "reflex")
    graph.add_edge("reflex", "gate")
    graph.add_edge("gate", "actuate")
    graph.add_edge("actuate", END)
    return graph.compile(checkpointer=InMemorySaver())
