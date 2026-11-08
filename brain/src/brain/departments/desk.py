"""The department desks: an agent team for Fire, Ambulance and medical, Traffic control (code MOBILITY), Disaster response and Utilities, the departments that used to be rules only.

The Police team plans around a suspect. A desk plans around a situation: an Analyst weighs what the incident's evidence and the city around it
support (using read-only tools: the city context, the playbook, the cascade and solver analyses), and a Chief decides whether the neighbouring
zones should be told, and which. Both can be language models; each has a scripted stand-in that answers the same way every time, and either takes
over when a model fails. The model never writes anything the public sees: the message is fixed by policy (`desks.messages`), and the only thing a
desk chooses is *where*, from zones the city graph says are near the incident. Code checks that (`verify_desk`), then the same gate that checks
every other action decides. Off by default (`team.departments`), so the Test Book decides as recorded.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field

from brain.departments import Manifest
from brain.departments.builder import IncidentClosed, TeamDeps
from brain.departments.facts import engine_facts, sentences
from brain.departments.team import PROMPTS, SCHEMAS, LLMCrew, ToolBox
from brain.graph.actuation import execute_approvals, gate_proposals, make_proposal

MAX_ZONES = 3
RADIUS_HOPS = 2
ANALYST_TOOLS = {
    "FIRE": ["graph.context", "kb.graph_search", "solver.plan_allocation"],
    "MEDICAL": ["graph.context", "kb.graph_search", "solver.plan_allocation"],
    "DISASTER": ["graph.context", "kb.graph_search", "graph.cascade", "math.time_to_threshold"],
    "MOBILITY": ["graph.context", "kb.graph_search", "graph.cascade"],
    "UTILITIES": ["graph.context", "kb.graph_search", "graph.cascade", "math.time_to_threshold"],
}


class DeskReport(BaseModel):
    severity: Literal["low", "medium", "high"]
    summary: str = Field(max_length=500)
    concerns: list[str] = Field(default_factory=list, max_length=4)
    advise_zones: list[str] = Field(default_factory=list, max_length=6)  # zones near the incident worth telling; from the city context only
    playbook_ids: list[str] = Field(default_factory=list, max_length=4)


class DeskDecision(BaseModel):
    send_advisory: bool
    zones: list[str] = Field(default_factory=list, max_length=6)
    justification: str = Field(max_length=500)
    playbook_ids: list[str] = Field(default_factory=list, max_length=4)


SCHEMAS["desk_analyst"], SCHEMAS["desk_chief"] = DeskReport, DeskDecision
PROMPTS["desk_analyst"] = """You are the Analyst of a city department's desk in an automated city-operations system (the brief names the department).
A rule engine has already responded to this incident. You judge the situation: how serious it is, and which nearby zones, if any, would be better off being told.
You have read-only tools over the city's live graph and the department playbook. Use the city context to find the zones near the incident; \
advise only zones the tools returned. If the brief has `facts` (an allocation, a level forecast, a shed plan, a cascade or the corridors), they were computed by solvers with certificates: use them, never contradict them, and mention the one that matters in your summary. Report what the tools returned, not what is typical: every statement in your summary and concerns must match a tool \
result or the brief. Always write zones as ids exactly as the tools give them (for example zone-06), never by name. Severity is high only when at least two independent sources agree or the playbook calls for it. You cannot send anything; you only advise."""
PROMPTS["desk_chief"] = """You are the Chief of a city department's desk. You receive the Analyst's report and the department playbook. Decide whether to \
send a public advisory to the neighbouring zones the Analyst named. You choose zones only; the wording of the advisory is fixed by city policy and you \
cannot change it. Write zones as ids (for example zone-06), never by name. Send only when the report says severity is high, choose at most three zones taken from the report, and cite the playbook ids that support it. \
When in doubt, do not send."""


def desk_advisory(message_for: dict[str, str], incident_type: str, zone_name: str) -> str:
    return message_for.get(incident_type, "An incident has been reported near {zone}. Follow the instructions of the emergency services.").format(zone=zone_name)


class ScriptedDesk:
    """Deterministic stand-ins: the same incident always gets the same assessment and the same decision."""

    mode = "scripted"

    async def analyst(self, brief: dict[str, Any], tools: ToolBox) -> DeskReport:
        sources = brief["independent_sources"]
        weight = brief["manifest_severity"]
        severity = "high" if weight >= 0.7 and sources >= 2 else "medium" if sources >= 1 and weight >= 0.5 else "low"
        zone = brief["incident"]["zone_id"]
        near = sorted(tools.store.zones.adj[zone]) if zone in tools.store.zones else []
        await tools.graph_context()  # the same read-only look the model would take; it is logged for the verifier
        said = sentences(brief.get("facts", {}))
        return DeskReport(severity=severity, summary=(f"{brief['incident']['type']} in {zone} with {sources} independent source(s); department weight {weight}. " + "; ".join(said))[:500].strip(),
                          concerns=[] if sources >= 2 else ["only one independent source so far"], advise_zones=near if severity == "high" else [],
                          playbook_ids=[i for i in brief["playbook_hint"] if tools.kb.has(i)][:2])

    async def chief(self, brief: dict[str, Any], tools: ToolBox) -> DeskDecision:
        report = brief["report"]
        send = report["severity"] == "high" and bool(report["advise_zones"])
        return DeskDecision(send_advisory=send, zones=report["advise_zones"][:MAX_ZONES] if send else [],
                            justification=("Two independent sources agree; telling the neighbouring zones. " if send else "Not serious enough to alert neighbours. ") + report["summary"][:300],
                            playbook_ids=report["playbook_ids"])


@dataclass
class DeskCrews:
    scripted: ScriptedDesk
    llm: dict[str, LLMCrew]  # department code -> its model crew (empty: scripted only)


def make_desk_crews(manifests: dict[str, Manifest], roles: dict[str, str], role_options: dict[str, dict[str, Any]], structured_output: str, use_llm: bool,
                    cassette: Any = None) -> DeskCrews:
    crews: dict[str, LLMCrew] = {}
    if use_llm:
        for code, tools in ANALYST_TOOLS.items():
            if code in manifests and manifests[code].agents:
                spec = manifests[code].agents
                crews[code] = LLMCrew(
                    {"desk_analyst": roles[spec["analyst"].model], "desk_chief": roles[spec["chief"].model]},
                    {"desk_analyst": list(spec["analyst"].tools or tools), "desk_chief": []}, structured_output,
                    role_options={"desk_analyst": role_options.get(spec["analyst"].model, {}), "desk_chief": role_options.get(spec["chief"].model, {})}, cassette=cassette)
    return DeskCrews(ScriptedDesk(), crews)


def verify_desk(decision: DeskDecision, report: DeskReport, *, store: Any, incident_zone: str, kb: Any, can_alert: bool) -> tuple[list[str], list[str], list[str]]:
    """(zones to tell, playbook ids that exist, problems). Nothing the model said reaches the public except a zone that passes here."""
    problems: list[str] = []
    if not decision.send_advisory:
        return [], [], problems
    if not can_alert:
        return [], [], ["the Twin cannot send alerts"]
    near = store.zones_within(incident_zone, RADIUS_HOPS)
    by_name = {str(store.zones.nodes[z].get("name", "")).lower(): z for z in store.zones.nodes}
    zones = []
    # A model often says 'Riverside' for zone-06: a name that matches exactly one zone is read as that zone; everything else is checked as it stands.
    for zone in dict.fromkeys(by_name.get(str(z).lower(), z) for z in decision.zones):
        if zone not in store.zones or zone not in near:
            problems.append(f"{zone!r} is not a zone within {RADIUS_HOPS} hops of {incident_zone}")
        elif len(zones) < MAX_ZONES:
            zones.append(zone)
        else:
            problems.append(f"more than {MAX_ZONES} zones asked for; {zone} dropped")
    if report.severity != "high":
        problems.append(f"the Analyst's severity is {report.severity}, not high: nothing is sent")
        zones = []
    cited = [i for i in decision.playbook_ids if kb.has(i)]
    if len(cited) != len(decision.playbook_ids):
        problems.append("a cited playbook item does not exist and was dropped")
    return zones, cited, problems


class DeskGraph:
    """What `Deliberations` runs for a desk: analyst, chief, verify, propose, gate, act, in that order."""

    def __init__(self, deps: TeamDeps, crews: DeskCrews, manifests: dict[str, Manifest]) -> None:
        self.deps, self.crews, self.manifests = deps, crews, manifests

    def _department(self, incident: Any) -> str | None:
        for code in incident.departments or []:
            if code in self.manifests and self.manifests[code].agents:
                return code
        return next((c for c, m in self.manifests.items() if m.agents and incident.type in m.incident_types), None)

    async def ainvoke(self, state: dict[str, Any], config: dict[str, Any] | None = None) -> dict[str, Any]:
        deps, act = self.deps, self.deps.actuation
        incident = deps.incidents[state["incident_id"]]
        code = self._department(incident)
        if code is None:
            if deps.policy.desks.escalate_to_person:
                act.timeline.emit("brain.human.needed", incident.incident_id, {
                    "why": "no_desk", "type": incident.type, "zone_id": incident.zone_id,
                    "detail": f"no department desk handles {incident.type}"}, state.get("trace_id") or None)
            return {"actions": [], "modes": {}, "case_file": {"recommendation": "no desk"}}
        manifest, store, timeline, trace = self.manifests[code], act.store, act.timeline, state.get("trace_id") or None
        tools = ToolBox(store, deps.kb, deps.policy, incident, code, deps.capabilities, incident.incident_id, stories=None, embedder=deps.embedder)
        crew = self.crews.llm.get(code)
        modes: dict[str, str] = {}

        def check_open() -> None:
            if deps.incidents[incident.incident_id].status == "closed":
                raise IncidentClosed(incident.incident_id)

        async def run(role: str, brief: dict[str, Any], schema_role: str) -> Any:
            started = time.monotonic()
            try:
                if crew is not None:
                    try:
                        answer = await crew._run(schema_role, brief, tools)
                        modes[role] = "llm"
                        return answer
                    except Exception as error:  # noqa: BLE001 - a desk role that fails falls back to its scripted stand-in
                        timeline.emit("brain.agent.fallback", incident.incident_id, {"role": f"{code}:{role}", "error": f"{type(error).__name__}: {str(error)[:300]}", "using": "scripted stand-in"}, trace)
                modes[role] = "scripted"
                return await getattr(self.crews.scripted, role)(brief, tools)
            finally:
                tools.usage.setdefault(schema_role, {})["seconds"] = round(time.monotonic() - started, 3)

        sources = {r.split("#")[0] for r in incident.evidence}
        zone_names = {z: store.zones.nodes[z].get("name", z) for z in store.zones.nodes}
        brief = {
            "department": manifest.name, "incident": {"incident_id": incident.incident_id, "type": incident.type, "zone_id": incident.zone_id},
            "evidence": incident.evidence, "independent_sources": len(sources), "manifest_severity": manifest.severity.get(incident.type, deps.policy.workspace.severity.get(incident.type, 0.5)),
            "playbook_hint": [i for i in sorted(deps.kb.items) if deps.kb.items[i].department == code and incident.type in deps.kb.items[i].applies_to][:4] if hasattr(deps.kb, "items") else [],
            "zones_near": sorted(store.zones_within(incident.zone_id, RADIUS_HOPS) - {incident.zone_id}),
        }
        if deps.policy.desks.escalate_to_person and hasattr(deps.kb, "items") and not brief["playbook_hint"]:
            # Nothing in the playbook is about this kind of incident. Use what the department does have; with nothing, ask for a person.
            brief["playbook_hint"] = [i for i in sorted(deps.kb.items) if deps.kb.items[i].department == code and deps.kb.items[i].kind == "playbook"][:4]
            if not brief["playbook_hint"]:
                timeline.emit("brain.human.needed", incident.incident_id, {
                    "why": "no_playbook", "type": incident.type, "zone_id": incident.zone_id, "department": code,
                    "detail": f"the {manifest.name} playbook has no procedure for {incident.type}"}, trace)
                return {"actions": [], "modes": {}, "case_file": {"recommendation": "watch"}, "blocked": []}
        facts = await engine_facts(code, incident, tools, deps)
        if facts:
            brief["facts"] = facts
        report = await run("analyst", brief, "desk_analyst")
        timeline.emit("brain.desk.assessed", incident.incident_id, {
            "department": code, "severity": report.severity, "summary": report.summary, "concerns": report.concerns, "advise_zones": report.advise_zones,
            **({"facts": facts} if facts else {}),
            "mode": modes["analyst"], "usage": {k: v for k, v in tools.usage.get("desk_analyst", {}).items() if k != "seconds"}}, trace,
            timing={"seconds": tools.usage.get("desk_analyst", {}).get("seconds", 0.0)})
        check_open()
        playbook = await tools.playbook_for([f"{incident.type} public advisory to neighbouring zones"]) if hasattr(tools, "playbook_for") else []
        decision = await run("chief", {**brief, "report": report.model_dump(), "playbook": playbook}, "desk_chief")
        zones, cited, problems = verify_desk(decision, report, store=store, incident_zone=incident.zone_id, kb=deps.kb,
                                             can_alert="broadcast_alert" in deps.capabilities and "broadcast_alert" in manifest.actuators)
        timeline.emit("brain.desk.decided", incident.incident_id, {
            "department": code, "send_advisory": decision.send_advisory, "asked_zones": decision.zones, "zones": zones, "problems": problems, "playbook": cited,
            "justification": decision.justification, "mode": modes["chief"]}, trace)
        check_open()
        proposals = []
        for zone in zones:
            proposal = make_proposal(
                act, incident, incident.evidence, "broadcast_alert",
                {"message": desk_advisory(deps.policy.desks.messages, incident.type, zone_names[zone]), "channel": deps.policy.tactics.alert_channel, "zone_id": zone},
                tier="deliberate", justification=f"{manifest.name} desk: {decision.justification}", knowledge_citations=cited, manifest=manifest)
            if proposal is not None:
                proposals.append(proposal.model_dump(mode="json"))
        approvals, blocked = await gate_proposals(act, proposals, [], trace) if proposals else ([], [])
        actions = await execute_approvals(act, approvals, trace) if approvals else []
        return {"actions": actions, "modes": modes, "case_file": {"recommendation": report.severity}, "blocked": blocked}
