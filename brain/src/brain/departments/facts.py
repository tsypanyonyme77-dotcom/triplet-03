"""What the solvers say about an incident, put in the brief of the team that reasons about it.

A model may or may not call a tool; the brief it is given it always reads. So the engines run here, in code, before the Analyst does, and
their answers (each from a solver with a certificate) are written into the brief as `facts`. The scripted Analyst reads them too. A solver
that fails or is off leaves its key out: the team then reasons as it did before. Nothing here sends anything; a proposal still goes to the gate.
"""

from __future__ import annotations

from typing import Any

from brain.contracts import Incident


async def engine_facts(code: str, incident: Incident, tools: Any, deps: Any) -> dict[str, Any]:
    policy, act, facts = deps.policy, deps.actuation, {}
    try:
        if code in ("FIRE", "MEDICAL") and policy.optimiser.dispatch == "on":
            result = await tools.solver_plan_allocation("fire" if code == "FIRE" else "ambulance")
            if "assignment" in result:
                facts["allocation"] = {"station_for_this_incident": result["assignment"].get(incident.incident_id), "assignment": result["assignment"],
                                       "cost": result["cost"], "nearest_first_cost": result["nearest_first_cost"], "status": result["status"]}
        if code == "DISASTER" and policy.math.kalman == "on" and deps.forecasts is not None:
            near = [f for f in deps.forecasts().values() if f["zone_id"] == incident.zone_id]
            if near:
                facts["forecast"] = near[0]
        if code == "UTILITIES" and incident.type == "overload":
            if policy.optimiser.shed == "on" and act.shedder is not None:
                planned = act.shedder.plan(act.store, incident.zone_id)
                if planned is not None:
                    feeder, shedding, _, _ = planned
                    facts["shed"] = {"feeder": feeder, "disconnect": shedding.disconnect, "load_removed_kw": shedding.load_removed_kw, "excess_kw": shedding.excess_kw,
                                     "impact": shedding.impact, "status": shedding.certificate.status}
            cascade = await tools.graph_cascade(incident.zone_id)
            facts["cascade"] = {"if_cut": cascade["cut"], "dark": cascade["dark"], "weight": cascade["weight"], "by_kind": cascade["by_kind"]}
        if code == "MOBILITY" and policy.orchestration.planner == "on" and act.corridors:
            facts["corridors"] = act.corridors[-3:]
    except Exception as error:  # noqa: BLE001 - a solver that cannot answer leaves the brief as it was
        act.timeline.emit("brain.solver.fallback", incident.incident_id, {"engine": "facts", "why": type(error).__name__, "used": "the brief without them"})
    return facts


def sentences(facts: dict[str, Any]) -> list[str]:
    """The facts in plain words, for the scripted Analyst's summary and the screen."""
    out = []
    if (a := facts.get("allocation")) is not None:
        saving = round(a["nearest_first_cost"] - a["cost"], 1) if a["cost"] is not None else 0
        out.append(f"the dispatch solver sends {a['station_for_this_incident'] or 'no unit'} here"
                   + (f", {saving} hops cheaper overall than nearest-first" if saving > 0 else ", the same as nearest-first"))
    if (f := facts.get("forecast")) is not None:
        when = f"about {f['seconds_to_threshold']} s to the {f['threshold_m']} m line" if f.get("seconds_to_threshold") else f"above the {f['threshold_m']} m line"
        out.append(f"the level forecast: {f['level_m']} m, rising {f['rate_m_per_min']} m/min, {when}")
    if (s := facts.get("shed")) is not None:
        out.append(f"the shed solver on {s['feeder']}: disconnect {', '.join(s['disconnect']) or 'nothing'}, {s['load_removed_kw']:.0f} of the {s['excess_kw']:.0f} kW excess, impact {s['impact']}")
    if (c := facts.get("cascade")) is not None:
        out.append(f"cutting {', '.join(c['if_cut'])} would darken {len(c['dark'])} facilities (impact {c['weight']})")
    if (corridors := facts.get("corridors")):
        out.append(f"{len(corridors)} emergency corridor{'s' if len(corridors) != 1 else ''} hold signals green on the roads")
    return out
