"""Building an explanation from the timeline log.

A decision, a held action or an incident is explained from the events the Brain wrote while it happened, plus the policy for the
thresholds and (when one is given) the knowledge base for titles. It never asks a model and never reads the live graph, so the same
log gives the same explanation, live or restored from a file.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from datetime import datetime
from typing import Any

from brain.config import Policy
from brain.explain.models import (
    Alternative,
    Cited,
    Counterfactual,
    Explanation,
    GateCheck,
    Margin,
    Step,
)

Row = dict[str, Any]

_READING = re.compile(r"^.+#\d+$")

# The canopy's region for each kind of event: the same edges `pulsesFor` draws in index.html (a test compares them).
REGION = {
    "brain.reading.received": "senses", "brain.reading.rejected": "senses", "brain.verdict.received": "senses",
    "brain.percept.surprise": "forward", "brain.incident.opened": "triage", "brain.incident.closed": "memory",
    "brain.suspect.assessed": "reflex", "brain.workspace.ignited": "workspace", "brain.workspace.released": "workspace",
    "brain.workspace.deferred": "workspace", "brain.pack.bid": "packs",
    "brain.deliberation.started": "team", "brain.deliberation.finished": "team", "brain.case.reviewed": "team",
    "brain.options.prepared": "team", "brain.plan.verified": "team", "brain.plan.compiled": "reflex",
    "brain.action.requested": "gate", "brain.action.blocked": "gate", "brain.action.result": "twin",
}  # the solvers' events (solver, shed, corridor, perimeter, forecast) fall to the default region: they explain a decision, they are not a stage
LAYER = {"brain.reading.received": "twin", "brain.action.result": "twin", "brain.verdict.received": "guardian"}

CHECK_PASSED = {
    "schema": lambda d, g: "the call matches the contract",
    "capability": lambda d, g: f"the Twin exposes {d.get('action')}",
    "allowlist": lambda d, g: f"{d.get('department')} may call {d.get('action')}",
    "incident": lambda d, g: "the incident takes new actions",
    "trust_ref": lambda d, g: f"verdict {d.get('trust_ref')} is trusted and covers a cited reading",
    "evidence": lambda d, g: (f"{len(g.get('witnesses', []))} independent trusted source{'' if len(g.get('witnesses', [])) == 1 else 's'} "
                              f"({', '.join(g.get('witnesses', []))}); {g.get('impact')}-impact needs {g.get('needed_sources')}"
                              + ("; a direct reading stands in" if g.get("direct") and len(g.get("witnesses", [])) < g.get("needed_sources", 0) else "")),
    "idempotency": lambda d, g: "no identical call was issued before",
    "cooling": lambda d, g: "the actuator was not driven a moment ago",
    "quarantine": lambda d, g: "the Guardian has not quarantined the actuator",
    "budget": lambda d, g: (f"action {g.get('budget', {}).get('incident_used', 0) + 1} of {g.get('budget', {}).get('incident_limit')} "
                            "for this incident"),
}


class _Log:
    def __init__(self, events: Iterable[Any]) -> None:
        self.rows: list[Row] = [e if isinstance(e, dict) else e.model_dump(mode="json") for e in events]
        self.t0 = self._at(self.rows[0]) if self.rows else 0.0
        self.zones: dict[str, str] = {}
        for row in self.rows:
            if row["type"] == "brain.started":
                self.zones = {z["id"]: z["name"] for z in (row["data"].get("topology") or {}).get("zones", [])}
        self.chain_head = self.rows[-1].get("hash", "") if self.rows else ""
        self.readings = {r.get("subject") for r in self.rows if r["type"] == "brain.reading.received"}
        self.verdicts = {r["data"].get("verdict_id") for r in self.rows if r["type"] == "brain.verdict.received"}

    @staticmethod
    def _at(row: Row) -> float:
        return datetime.fromisoformat(row["time"].replace("Z", "+00:00")).timestamp()

    def zone(self, zone_id: str | None) -> str:
        return self.zones.get(zone_id, zone_id or "an unknown zone")

    def find(self, type: str, test: Callable[[Row], bool]) -> int | None:
        return next((i for i, r in enumerate(self.rows) if r["type"] == type and test(r)), None)

    def last_before(self, index: int, type: str, test: Callable[[Row], bool] = lambda r: True) -> int | None:
        return next((i for i in range(index - 1, -1, -1) if self.rows[i]["type"] == type and test(self.rows[i])), None)

    def about(self, readings: Iterable[str], before: int) -> set[int]:
        """The reading, its verdict and any surprise it caused."""
        wanted = set(readings)
        return {i for i, r in enumerate(self.rows[:before])
                if r.get("subject") in wanted and r["type"] in ("brain.reading.received", "brain.verdict.received", "brain.percept.surprise")}

    def verdict_for(self, reading_id: str) -> Row | None:
        return next((r for r in self.rows if r["type"] == "brain.verdict.received" and r.get("subject") == reading_id), None)


def action_phrase(action: str, params: dict[str, Any], zone: Callable[[str | None], str]) -> str:
    if action == "dispatch_unit":
        kind, mode = params.get("unit_type", "a"), params.get("mode") or "respond"
        if mode == "pursuit":
            return f"Send a {kind} unit to pursue {params.get('target_id', 'the suspect')} from {zone(params.get('zone_id'))}"
        if mode == "contain":
            return f"Send a {kind} unit to hold {zone(params.get('zone_id'))}"
        return f"Send a {kind} unit to {zone(params.get('zone_id'))}"
    if action == "broadcast_alert":
        return f"Warn the public in {zone(params.get('zone_id'))}"
    if action == "set_valve_state":
        return f"Set valve {params.get('valve_id')} to {params.get('state')}"
    if action == "set_signal_phase":
        return f"Change the signal at {params.get('node_id') or zone(params.get('zone_id'))}"
    if action == "set_grid_connection":
        return f"Switch grid connection {params.get('connection_id') or params.get('node_id') or ''}".strip()
    if action == "recall_unit":
        return f"Recall unit {params.get('unit_id')}"
    return action.replace("_", " ").capitalize()


def _ordinal(n: int) -> str:
    return {1: "first", 2: "second", 3: "third", 4: "fourth", 5: "fifth"}.get(n, f"{n}th")


def _close(observed: float, threshold: float, unit: str, *, needs_at_least: bool = True) -> str:
    gap = abs(observed - threshold)
    side = "above" if observed >= threshold else "below"
    wanted = "needed" if needs_at_least else "allowed"
    unit = f" {unit}" if unit else ""
    return f"{observed:g}{unit} is {gap:.2g}{unit} {side} the {threshold:g} {wanted}" if gap else f"{observed:g}{unit} is exactly the {threshold:g} {wanted}"


def _classify(item: str) -> str:
    if item.startswith("CAP-"):
        return "capability"
    if item.startswith("REF-"):
        return "reference"
    if "-PB-" in item:
        return "playbook"
    return "rule" if re.match(r"^[A-Z]+-\d+$", item) else "other"


def _fact(log: _Log, row: Row) -> tuple[str, list[str]]:
    d, t, sub = row["data"], row["type"], row.get("subject") or ""
    zone = log.zone
    if t == "brain.reading.received":
        return f"A {str(d.get('type', 'sensor')).replace('_', ' ')} reading arrived from {d.get('sensor_id')}: {d.get('summary')}.", [sub]
    if t == "brain.verdict.received":
        why = f" ({', '.join(d['reasons'])})" if d.get("reasons") else ""
        return f"The Guardian judged {sub} {d.get('status')}{why}.", [sub, d.get("verdict_id")]
    if t == "brain.percept.surprise":
        doubted = " It was doubted until another reading agreed." if d.get("doubted") else ""
        return (f"{d.get('sensor_id')} read {d.get('observed'):g} where about {d.get('expected'):g} was expected: "
                f"{d.get('z'):g} spreads off, the doubt line is {d.get('threshold'):g}.{doubted}"), [sub]
    if t == "brain.incident.opened":
        return f"A {d.get('type')} incident opened in {zone(d.get('zone_id'))}, on {len(d.get('evidence', []))} reading{'' if len(d.get('evidence', [])) == 1 else 's'}.", [sub, *d.get("evidence", [])]
    if t == "brain.workspace.ignited":
        slot = "and took an attention slot" if d.get("slot") else "and was lit without a slot"
        return f"Attention lit the incident at salience {d.get('salience'):g} {slot}.", [sub]
    if t == "brain.pack.bid":
        return f"The departments bid; {', '.join(d.get('recruited', [])) or 'nobody'} answered.", [sub]
    if t == "brain.suspect.assessed":
        names = ", ".join(f["name"] for f in d.get("features", []))
        return f"{d.get('entity_id')} scored {d.get('score'):g} ({d.get('level')}) on {names}.", [sub]
    if t == "brain.deliberation.started":
        return f"The agent team started on {d.get('entity_id')} ({d.get('crew')} crew, {d.get('budget_s'):g} s budget).", [sub]
    if t == "brain.case.reviewed":
        return f"The Analyst recommended '{d.get('recommendation')}' with {d.get('confidence')} confidence: {d.get('summary')}", [sub]
    if t == "brain.options.prepared":
        return f"The Tactician offered {len(d.get('options', []))} options: {', '.join(o['name'] for o in d.get('options', []))}.", [sub]
    if t == "brain.plan.verified":
        return f"The Chief chose {d.get('option')}, and the checks found {len(d.get('problems', [])) or 'no'} problem{'' if len(d.get('problems', [])) == 1 else 's'}: {d.get('justification')}", [sub]
    if t == "brain.decision.made":
        return f"Decision {d.get('decision_id')} ({d.get('tier')}): {action_phrase(d.get('action', ''), d.get('params', {}), zone)}. {d.get('justification')}", [sub, d.get("decision_id")]
    if t == "brain.action.requested":
        return f"The gate signed the call to {d.get('actuator_id')} and sent it.", [sub, d.get("decision_id")]
    if t == "brain.action.result":
        unit = f", unit {d['unit_id']}" if d.get("unit_id") else ""
        return f"The Twin answered '{d.get('status')}'{unit}.", [sub, d.get("decision_id")]
    if t == "brain.action.blocked":
        return f"Held at the {d.get('stage')}: {d.get('reason')}", [sub]
    if t == "brain.incident.closed":
        return f"The incident closed: {d.get('outcome')}.", [sub]
    if t == "brain.solver.solved":  # a solver's certificate: what it chose, what the old rule would have chosen, and what that saves
        saves = f", {d.get('regret_vs_nearest'):g} cheaper than nearest-first" if (d.get("regret_vs_nearest") or 0) > 0 else ", the same as nearest-first"
        return (f"The dispatch solver ({d.get('status')}, inputs {d.get('inputs_hash')}) chose {d.get('station')} over {d.get('nearest')} for the nearest-first rule; "
                f"total cost {d.get('objective'):g} against {d.get('nearest_objective'):g}{saves}."), [sub]
    if t == "brain.shed.planned":
        return (f"The shed solver on {d.get('feeder')} chose to disconnect {', '.join(d.get('disconnect', [])) or 'nothing'}: {d.get('load_removed_kw'):g} of the "
                f"{d.get('excess_kw'):g} kW excess, impact {d.get('impact'):g} ({d.get('status')}, inputs {d.get('inputs_hash')})."), [sub]
    if t == "brain.corridor.opened":
        return (f"The corridor planner held {len(d.get('signals', []))} signals green along {' > '.join(d.get('path', []))}: {d.get('eta_s'):g} s against {d.get('plain_eta_s'):g} s "
                f"by the plain path (inputs {d.get('inputs_hash')})."), [sub]
    if t == "brain.perimeter.checked":
        return (f"The perimeter solver says {d.get('optimal_units')} units would hold; the team uses {d.get('team_units')}"
                + (f", and the solver's cut holds with probability {d.get('robust_p'):g}" if d.get("robust_p") is not None else "") + "."), [sub]
    if t == "brain.forecast.warned":
        return (f"The level forecast saw {d.get('sensor_id')} at {d.get('level_m'):g} m rising {d.get('rate_m_per_min'):g} m/min, about {d.get('seconds_to_threshold')} s "
                f"from the {d.get('threshold_m'):g} m line, and warned the zone before it was crossed."), [sub]
    return t.removeprefix("brain.").replace(".", " "), [sub]


def _steps(log: _Log, indexes: Iterable[int]) -> list[Step]:
    steps = []
    for n, i in enumerate(sorted(set(indexes)), 1):
        row = log.rows[i]
        fact, ids = _fact(log, row)
        tier = row["data"].get("tier")
        region = ("reflex" if tier == "reflex" else "team") if row["type"] == "brain.decision.made" else REGION.get(row["type"], "gate")
        steps.append(Step(
            n=n, layer=LAYER.get(row["type"], "brain"), region=region, event_type=row["type"], event_id=row["id"],
            at_ms=round((log._at(row) - log.t0) * 1000), fact=fact, ids=[x for x in dict.fromkeys(ids) if x],
        ))
    return steps


def _cited(log: _Log, data: Row, kb: Any, plan: Row | None = None) -> list[Cited]:
    titles: dict[str, str] = {}
    for row in log.rows:
        if row["type"] == "brain.plan.verified":
            titles.update(row["data"].get("playbook_titles", {}))
    found: dict[str, str] = {}  # id -> how the team's search found it
    for lookup in (plan or {}).get("retrieval", []):
        for hit in lookup["hits"]:
            found.setdefault(hit["id"], f"found by {' and '.join(hit['why'])} for the question '{lookup['query']}'")
    cited = [data.get("rule_id"), *data.get("knowledge", []), *(c for c in data.get("citations", []) if not _READING.match(c) and not c.startswith("verdict-"))]
    out = []
    for item in dict.fromkeys(x for x in cited if x):
        title = titles.get(item) or (kb.title(item) if kb is not None else None)
        out.append(Cited(id=item, kind=_classify(item), title=title, why=[found.get(item, "cited by the decision")],
                         resolved=kb.has(item) if kb is not None else None))
    return out


def _unresolved(log: _Log, readings: Iterable[str], verdicts: Iterable[str | None]) -> list[str]:
    missing = [r for r in readings if r not in log.readings] + [v for v in verdicts if v and v not in log.verdicts]
    return sorted(set(missing))


def for_target_id(row: Row, target: str | None) -> bool:
    return row["data"].get("entity_id") == target


def explain_decision(events: Iterable[Any], decision_id: str, *, policy: Policy | None = None, kb: Any = None) -> Explanation:
    """Why one decision was taken. Raises KeyError for an id the log does not hold."""
    log, policy = _Log(events), policy or Policy()
    i = log.find("brain.decision.made", lambda r: r["data"].get("decision_id") == decision_id)
    if i is None:
        raise KeyError(decision_id)
    row = log.rows[i]
    d, incident, params = row["data"], row["subject"], row["data"].get("params", {})
    evidence = list(d.get("evidence") or [c for c in d.get("citations", []) if _READING.match(c)])
    target = params.get("target_id")
    pick = {i} | log.about(evidence, i)
    plan_at = log.last_before(i, "brain.plan.verified", lambda r: r.get("subject") == incident and for_target_id(r, target)) if d.get("tier") == "deliberate" else None
    plan_row = log.rows[plan_at]["data"] if plan_at is not None else None
    for type in ("brain.incident.opened", "brain.workspace.ignited", "brain.pack.bid", "brain.solver.solved", "brain.shed.planned", "brain.corridor.opened", "brain.perimeter.checked"):
        if (j := log.last_before(i, type, lambda r: r.get("subject") == incident)) is not None:
            pick.add(j)
    if incident.startswith("watch-") and (j := log.last_before(i, "brain.forecast.warned", lambda r: f"watch-{r.get('subject')}" == incident)) is not None:
        pick.add(j)  # the early alert belongs to no incident: its subject is the watch on the sensor
    for_target = lambda r: r["data"].get("entity_id") == target  # noqa: E731
    if target and (j := log.last_before(i, "brain.suspect.assessed", lambda r: r.get("subject") == incident and for_target(r))) is not None:
        pick.add(j)
    if d.get("tier") == "deliberate" and target:
        for type in ("brain.deliberation.started", "brain.case.reviewed", "brain.options.prepared", "brain.plan.verified"):
            if (j := log.last_before(i, type, lambda r: r.get("subject") == incident and for_target(r))) is not None:
                pick.add(j)
    pick |= {j for j, r in enumerate(log.rows) if j > i and r["type"] in ("brain.action.requested", "brain.action.result")
             and r["data"].get("decision_id") == decision_id}

    gate = d.get("gate") or {}
    checks = [GateCheck(check=name, passed=True, reason=CHECK_PASSED[name](d, gate)) for name in gate.get("checks", []) if name in CHECK_PASSED]
    margins = _margins(log, i, d, gate, policy)
    return Explanation(
        subject="decision", id=decision_id, outcome="acted",
        headline=f"{action_phrase(d.get('action', ''), params, log.zone)}: {d.get('justification')}",
        steps=_steps(log, pick), checks=checks, knowledge=_cited(log, d, kb, plan_row), margins=margins,
        alternatives=_alternatives(log, i, incident, target) if d.get("tier") == "deliberate" else [],
        counterfactuals=_counterfactuals_acted(d, gate, margins),
        unresolved=_unresolved(log, evidence, [d.get("trust_ref")]), config_hash=d.get("config_hash", ""), log_chain_head=log.chain_head,
    )


def _margins(log: _Log, i: int, d: Row, gate: Row, policy: Policy) -> list[Margin]:
    out = []
    incident, target = log.rows[i]["subject"], d.get("params", {}).get("target_id")
    if target and (j := log.last_before(i, "brain.suspect.assessed", lambda r: r.get("subject") == incident and r["data"].get("entity_id") == target)) is not None:
        score, line = log.rows[j]["data"]["score"], policy.scoring.suspect_threshold
        out.append(Margin(name="suspect score", observed=score, threshold=line, unit="of 1", how_close=_close(score, line, "", needs_at_least=True).strip()))
    if (j := log.last_before(i, "brain.workspace.ignited", lambda r: r.get("subject") == incident)) is not None:
        salience, line = log.rows[j]["data"]["salience"], policy.workspace.ignite_at
        out.append(Margin(name="salience", observed=salience, threshold=line, unit="of 1", how_close=_close(salience, line, "").strip()))
    if gate.get("witnesses") is not None:
        found, needed = len(gate["witnesses"]), gate.get("needed_sources", 0)
        out.append(Margin(name="independent sources", observed=found, threshold=needed, unit="sources", how_close=_close(found, needed, "sources")))
    if gate.get("budget"):
        used, limit = gate["budget"]["incident_used"] + 1, gate["budget"]["incident_limit"]
        out.append(Margin(name="actions in the incident", observed=used, threshold=limit, unit="actions", how_close=_close(used, limit, "actions", needs_at_least=False)))
    return out


def _alternatives(log: _Log, i: int, incident: str, target: str | None) -> list[Alternative]:
    options = log.last_before(i, "brain.options.prepared", lambda r: r.get("subject") == incident and r["data"].get("entity_id") == target)
    plan = log.last_before(i, "brain.plan.verified", lambda r: r.get("subject") == incident and r["data"].get("entity_id") == target)
    if options is None:
        return []
    chosen = log.rows[plan]["data"].get("option") if plan is not None else None
    return [Alternative(name=o["name"], chosen=o["name"] == chosen, rationale=o.get("rationale", "")) for o in log.rows[options]["data"].get("options", [])]


def _counterfactuals_acted(d: Row, gate: Row, margins: list[Margin]) -> list[Counterfactual]:
    out = [Counterfactual(change=f"Verdict {d.get('trust_ref')} being anything but trusted", would_flip=True,
                          basis="the gate signs a call only if its trust_ref names a trusted verdict that covers a cited reading")]
    sources = next((m for m in margins if m.name == "independent sources"), None)
    if sources and sources.observed == sources.threshold and not gate.get("direct"):
        out.append(Counterfactual(change=f"One of the {int(sources.threshold)} independent sources missing", would_flip=True,
                                  basis=f"{gate.get('impact')}-impact actions need {int(sources.threshold)} independent trusted sources"))
    budget = next((m for m in margins if m.name == "actions in the incident"), None)
    if budget and budget.observed == budget.threshold:
        out.append(Counterfactual(change="One more earlier action in this incident", would_flip=True,
                                  basis=f"the incident's budget is {int(budget.threshold)} actions"))
    score = next((m for m in margins if m.name == "suspect score"), None)
    if score and score.observed - score.threshold < 0.1 * score.threshold:
        out.append(Counterfactual(change=f"A suspect score under {score.threshold:g}", would_flip=True,
                                  basis=f"the reflex pursues only at {score.threshold:g} or more; this one was {score.observed:g}"))
    return out


def explain_held(events: Iterable[Any], event_id: str, *, policy: Policy | None = None, kb: Any = None) -> Explanation:
    """Why an action was held back. `event_id` is the id of the `brain.action.blocked` event. Raises KeyError for an unknown id."""
    log = _Log(events)
    i = log.find("brain.action.blocked", lambda r: r["id"] == event_id)
    if i is None:
        raise KeyError(event_id)
    row = log.rows[i]
    d, incident, params = row["data"], row["subject"], row["data"].get("params", {})
    evidence = list(d.get("evidence") or [e["reading_id"] for e in d.get("discounted_evidence", [])])
    if not evidence and row.get("traceid"):
        evidence = [row["traceid"].rsplit(":", 1)[0] + "#" + row["traceid"].rsplit(":", 1)[1]]
    evidence = [e for e in evidence if e in log.readings] + [e for e in evidence if e not in log.readings]
    pick = {i} | log.about(evidence, i)
    for type in ("brain.incident.opened", "brain.workspace.ignited"):
        if (j := log.last_before(i, type, lambda r: r.get("subject") == incident)) is not None:
            pick.add(j)
    gate = d.get("gate") or {}
    checks = [GateCheck(check=name, passed=True, reason=CHECK_PASSED[name]({**d, "action": d.get("would_have"), "trust_ref": d.get("trust_ref")}, gate))
              for name in gate.get("checks", []) if name in CHECK_PASSED]
    checks.append(GateCheck(check=d.get("check", ""), passed=False, reason=d.get("reason", "")))
    margins = []
    if gate.get("witnesses") is not None and gate.get("needed_sources") is not None:
        found, needed = len(gate["witnesses"]), gate["needed_sources"]
        margins.append(Margin(name="independent sources", observed=found, threshold=needed, unit="sources", how_close=_close(found, needed, "sources")))
    would = action_phrase(d.get("would_have", ""), params, log.zone)
    first_decision = next((r["data"].get("config_hash", "") for r in log.rows if r["type"] == "brain.decision.made"), "")
    return Explanation(
        subject="held", id=event_id, outcome="held", headline=f"Held: {would[0].lower()}{would[1:]}. {d.get('reason')}",
        steps=_steps(log, pick), checks=checks, margins=margins, counterfactuals=_counterfactuals_held(d, gate, evidence),
        unresolved=_unresolved(log, evidence, [d.get("trust_ref")]), config_hash=first_decision, log_chain_head=log.chain_head,
    )


def held_counterfactuals(blocked: Row) -> list[Counterfactual]:
    """The changes that would have released a held action, from the data of its `brain.action.blocked` event."""
    return _counterfactuals_held(blocked, blocked.get("gate") or {}, [])


def _counterfactuals_held(d: Row, gate: Row, evidence: list[str]) -> list[Counterfactual]:
    check = d.get("check", "")
    if check == "trust":
        return [Counterfactual(change=f"{e['reading_id']} being trusted by the Guardian (it was {e['status']})", would_flip=True, basis=d.get("reason", ""))
                for e in d.get("discounted_evidence", [])]
    if check == "evidence":
        found, needed = len(gate.get("witnesses", [])), gate.get("needed_sources", 0)
        if not needed and (said := re.search(r"needs (\d+) independent trusted sources, found (\d+)", d.get("reason", ""))):
            needed, found = int(said[1]), int(said[2])  # a log written before the gate recorded its facts (before 2 Nov 2026)
        return [Counterfactual(change=f"A {_ordinal(found + 1)} independent trusted source ({found} found, {needed} needed)", would_flip=True,
                               basis=f"{gate.get('impact', 'this')}-impact actions need {needed} independent trusted sources")]
    if check == "human_approval":
        return [Counterfactual(change="A human approval of this action", would_flip=False,
                               basis="human approval is not wired up yet, so no change in the evidence could release it")]
    if check == "trust_ref":
        return [Counterfactual(change=f"Verdict {gate.get('verdict_id')} being trusted by the Guardian (it was {gate.get('verdict_status')})", would_flip=True, basis=d.get("reason", ""))]
    if check == "budget":
        return [Counterfactual(change=f"Fewer than {gate.get('limit')} earlier actions in this {gate.get('scope')}", would_flip=True, basis=d.get("reason", ""))]
    if check == "cooling":
        return [Counterfactual(change=f"{gate.get('min_gap_s'):g} s since the actuator was last driven (it was {gate.get('seconds_ago')} s)", would_flip=True, basis=d.get("reason", ""))]
    if check == "quarantine":
        return [Counterfactual(change="The Guardian releasing its quarantine of the actuator", would_flip=True, basis=d.get("reason", ""))]
    if check == "resources":
        return [Counterfactual(change="A station with a unit available", would_flip=True, basis=d.get("reason", ""))]
    if check == "surprise":
        return [Counterfactual(change="A second reading, or another source, agreeing with the surprising one", would_flip=True, basis=d.get("reason", ""))]
    if check in ("capability", "allowlist", "incident", "schema"):
        return [Counterfactual(change=f"The {check} check being met", would_flip=True, basis=d.get("reason", ""))]
    return []


def explain_incident(events: Iterable[Any], incident_id: str, *, policy: Policy | None = None, kb: Any = None) -> Explanation:
    """The story of one incident from its first reading to its close (or to now, if it is still open)."""
    log = _Log(events)
    opened = log.find("brain.incident.opened", lambda r: r.get("subject") == incident_id)
    if opened is None:
        raise KeyError(incident_id)
    evidence = log.rows[opened]["data"].get("evidence", [])
    story = {"brain.incident.opened", "brain.workspace.ignited", "brain.workspace.released", "brain.workspace.deferred", "brain.pack.bid",
             "brain.suspect.assessed", "brain.deliberation.started", "brain.plan.verified", "brain.decision.made", "brain.action.blocked",
             "brain.action.result", "brain.incident.closed"}
    pick = log.about(evidence, opened) | {i for i, r in enumerate(log.rows) if r.get("subject") == incident_id and r["type"] in story}
    decisions = [r for r in log.rows if r["type"] == "brain.decision.made" and r.get("subject") == incident_id]
    held = [r for r in log.rows if r["type"] == "brain.action.blocked" and r.get("subject") == incident_id]
    closed = next((r for r in log.rows if r["type"] == "brain.incident.closed" and r.get("subject") == incident_id), None)
    data = log.rows[opened]["data"]
    ended = f"closed: {closed['data'].get('outcome')}" if closed else "still open"
    knowledge: dict[str, Cited] = {}
    for r in decisions:
        for c in _cited(log, r["data"], kb):
            knowledge.setdefault(c.id, c)
    plural = lambda n, word: f"{n} {word}{'' if n == 1 else 's'}"  # noqa: E731
    return Explanation(
        subject="incident", id=incident_id, outcome="closed" if closed else "open",
        headline=f"{str(data.get('type')).capitalize()} in {log.zone(data.get('zone_id'))}: {plural(len(decisions), 'action')} taken, {len(held)} held, {ended}.",
        steps=_steps(log, pick), knowledge=list(knowledge.values()), unresolved=_unresolved(log, evidence, []),
        config_hash=decisions[0]["data"].get("config_hash", "") if decisions else "", log_chain_head=log.chain_head,
    )
