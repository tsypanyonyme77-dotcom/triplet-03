"""The reflex path for incidents that are not crimes: a flood, a jam, a fire, an accident.

A `condition` rule fires once for each open incident of its type and may name a device (a signal
controller, a valve) that the Twin must have in reach. No rule here decides *whether* the action is
allowed: it only proposes, and the gate disposes.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from brain.contracts import Incident, VerdictStatus
from brain.departments import Rule, matches, render
from brain.graph.actuation import Actuation, make_proposal

# The facility an action works on, for actions that act on a device rather than on a zone.
DEVICE_KINDS = {"set_signal_phase": "signal_controller", "set_valve_state": "valve", "set_grid_connection": "grid_breaker"}

_TYPE_NAMES = {"jam": "Traffic jam", "flood": "Flood", "fire": "Fire", "accident": "Accident"}


def _only_doubted_evidence(act: Actuation, incident: Incident, doubted: Callable[[str], bool]) -> list[str]:
    """The trusted evidence readings, if every one of them is doubted (nothing independent agrees with them)."""
    trusted = [r for r in incident.evidence if (v := act.store.verdict_of(r)) is not None and v.status == VerdictStatus.TRUSTED]
    return trusted if trusted and all(doubted(r) for r in trusted) else []


def _shed(act: Actuation, rule: Rule, incident: Incident, trace_id: str | None) -> list[dict[str, Any]] | None:
    """An overload on a known feeder: disconnect the zones that remove the excess at the least impact, instead of the overloaded zone itself.
    None when the zone is on no known feeder (the plain rule then applies)."""
    planned = act.shedder.plan(act.store, incident.zone_id)
    if planned is None:
        return None
    feeder, shedding, loads, impact = planned
    if not shedding.disconnect:
        return None  # the feeder as a whole is not over its target: the overloaded substation's own rule applies
    act.timeline.emit("brain.shed.planned", incident.incident_id, {
        "feeder": feeder, "disconnect": shedding.disconnect, "load_removed_kw": shedding.load_removed_kw, "excess_kw": shedding.excess_kw, "impact": shedding.impact,
        "status": shedding.certificate.status, "loads_kw": dict(sorted(loads.items())), "impact_by_zone": dict(sorted(impact.items())),
        "inputs_hash": shedding.certificate.inputs_hash}, trace_id, timing={"elapsed_ms": shedding.certificate.elapsed_ms})
    out = []
    for zone in shedding.disconnect:
        device = act.store.nearest_facility(zone, "grid_breaker")
        if device is None:
            continue
        proposal = make_proposal(
            act, incident, incident.evidence, "set_grid_connection", {"zone_id": zone, "state": "disconnected"}, tier="reflex",
            justification=f"Overload in {incident.zone_id} on {feeder}: disconnecting {zone} removes {loads.get(zone, 0):.0f} kW of the {shedding.excess_kw:.0f} kW excess "
                          f"at an impact of {impact.get(zone, 0):.0f}; the least of any set that is enough. Rule {rule.id}.",
            rule_id=rule.id, manifest=act.manifests.get(rule.department or "", act.manifest), actuator_id=device["actuator_id"])
        if proposal is not None:
            out.append(proposal.model_dump(mode="json"))
    return out


async def condition_proposals(
    act: Actuation, rules: list[Rule], incident: Incident, blocked: list[str], trace_id: str | None,
    doubted: Callable[[str], bool] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Proposals for one open non-crime incident, and the dedupe keys of the blocks reported this time.

    When the only trusted evidence is a reading the forward models doubt (it jumped far outside its sensor's
    history and nothing else agrees yet), nothing is proposed: the Brain says so and waits for a second source
    or for the sensor's next reading to confirm it.
    """
    proposals: list[dict[str, Any]] = []
    new_blocked: list[str] = []
    held = _only_doubted_evidence(act, incident, doubted) if doubted is not None else []
    for rule in rules:
        if held and rule.scope == "condition" and matches(rule, {"incident": incident.model_dump(mode="json"), "device": {}}):
            key = f"surprise|{incident.incident_id}"
            if key not in blocked and key not in new_blocked:
                new_blocked.append(key)
                sensors = sorted({r.split("#")[0] for r in held})
                act.timeline.emit(
                    "brain.action.blocked", incident.incident_id,
                    {"stage": "reflex", "check": "surprise", "would_have": rule.do[0].action,
                     "reason": f"{len(held)} {'reading' if len(held) == 1 else 'readings'} from {', '.join(sensors)} jumped far outside "
                               f"the sensor's own history and no other source agrees yet"},
                    trace_id,
                )
            continue
        context = {"incident": incident.model_dump(mode="json"), "device": {}}
        if rule.scope != "condition" or not matches(rule, context):
            continue
        for template in rule.do:
            kind = DEVICE_KINDS.get(template.action)
            device = act.store.nearest_facility(incident.zone_id, kind) if kind else None
            if kind and device is None:
                key = f"resources|{incident.incident_id}|{rule.id}"
                if key not in blocked and key not in new_blocked:
                    new_blocked.append(key)
                    act.timeline.emit(
                        "brain.action.blocked", incident.incident_id,
                        {"stage": "reflex", "check": "resources", "would_have": template.action,
                         "reason": f"no {kind.replace('_', ' ')} in reach"},
                        trace_id,
                    )
                continue
            context["device"] = device or {}
            if act.shedder is not None and template.action == "set_grid_connection":
                shed_proposals = _shed(act, rule, incident, trace_id)
                if shed_proposals is not None:
                    proposals.extend(shed_proposals)
                    continue
            proposal = make_proposal(
                act, incident, incident.evidence, template.action, render(template, context), tier="reflex",
                justification=f"{_TYPE_NAMES.get(incident.type, incident.type.capitalize())} reported in {incident.zone_id} "
                              f"({', '.join(incident.evidence)}). Rule {rule.id}.",
                rule_id=rule.id, manifest=act.manifests.get(rule.department or "", act.manifest),
                actuator_id=device["actuator_id"] if device else None,
            )
            if proposal is not None:
                proposals.append(proposal.model_dump(mode="json"))
            elif (key := f"resources|{incident.incident_id}|{rule.id}") not in blocked and key not in new_blocked:
                new_blocked.append(key)
                act.timeline.emit(
                    "brain.action.blocked", incident.incident_id,
                    {"stage": "reflex", "check": "resources", "would_have": template.action,
                     "reason": "no station has a unit available"},
                    trace_id,
                )
    return proposals, new_blocked
