"""Compile a department manifest into its deliberation graph, and run deliberations in the background.

    analyst -> tactician -> chief -> verify -> propose -> gate -> actuate
                   ^                    |
                   +---- revise --------+     (the verifier's objections go back once)

The reflex tier never waits for this graph. It asks for a deliberation and carries on;
whatever the team decides goes through the same gate as a reflex rule.
"""

from __future__ import annotations

import asyncio
import operator
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated, Any, TypedDict

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from brain import clock
from brain.config import ModelsConfig, Policy
from brain.contracts import Assessment, CctvAnomaly, Incident
from brain.departments import Manifest
from brain.departments.team import (
    CaseFile,
    ChiefDecision,
    LLMCrew,
    ScriptedCrew,
    TacticalOption,
    ToolBox,
    VerifiedPlan,
    _position,
    units_free,
    verify_case,
    verify_plan,
)
from brain.graph.actuation import Actuation, execute_approvals, gate_proposals, make_proposal
from brain.knowledge import KnowledgeBase
from brain.timeline import Timeline
from brain.tools import geo


def _merge(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    return {**left, **right}


class TeamState(TypedDict, total=False):
    incident_id: str
    entity_id: str
    # "plan": a pursuit is under way. "replan": its perimeter was outrun. "ambiguous": the rules could not decide.
    reason: str
    trace_id: str
    assessment: dict[str, Any]
    case_file: dict[str, Any]
    pursue: bool  # the team itself must launch the pursuit (ambiguous cases only)
    options: list[dict[str, Any]]
    planned_from: str  # the zone the Tactician planned around
    decision: dict[str, Any]
    plan: dict[str, Any]
    feedback: list[str]
    revision: int
    proposals: list[dict[str, Any]]
    approvals: list[dict[str, Any]]
    modes: Annotated[dict[str, str], _merge]  # role -> llm | scripted
    blocked: Annotated[list[str], operator.add]
    actions: Annotated[list[dict[str, Any]], operator.add]


@dataclass
class TeamDeps:
    actuation: Actuation
    policy: Policy
    kb: KnowledgeBase
    incidents: dict[str, Incident]
    capabilities: set[str]
    scripted: ScriptedCrew
    llm: LLMCrew | None = None
    max_revisions: int = 1
    toolboxes: dict[str, ToolBox] = field(default_factory=dict)
    stories: Callable[[], list[Any]] | None = None
    embedder: Any = None
    relative_times: bool = False
    forecasts: Callable[[], dict[str, dict[str, Any]]] | None = None  # the level forecasts, per water sensor


class IncidentClosed(Exception):
    """The incident ended while its team was still deliberating: nothing is left to plan for."""



def _tokens(tools: ToolBox, role: str) -> dict[str, Any]:
    """What a role's run cost in tokens and calls. Seconds are not here: measured time goes in the event's `timing`."""
    return {key: value for key, value in tools.usage.get(role, {}).items() if key != "seconds"}


def _timing(tools: ToolBox, role: str) -> dict[str, float] | None:
    seconds = tools.usage.get(role, {}).get("seconds")
    return {"seconds": seconds} if seconds is not None else None


def build_department(manifest: Manifest, deps: TeamDeps):
    act = deps.actuation
    store, timeline = act.store, act.timeline
    kind = manifest.facility_type or ""

    def open_incident(state: TeamState) -> Incident:
        incident = deps.incidents[state["incident_id"]]
        if incident.status == "closed":
            raise IncidentClosed(incident.incident_id)
        return incident

    def toolbox(state: TeamState, config: RunnableConfig) -> ToolBox:
        key = config["configurable"]["thread_id"]
        if key not in deps.toolboxes:
            deps.toolboxes[key] = ToolBox(
                store, deps.kb, deps.policy, deps.incidents[state["incident_id"]], manifest.code,
                deps.capabilities, state["entity_id"], stories=deps.stories, embedder=deps.embedder,
            )
        return deps.toolboxes[key]

    async def run_role(role: str, brief: dict[str, Any], tools: ToolBox, state: TeamState) -> tuple[Any, str]:
        started = time.monotonic()
        try:
            if deps.llm is not None:
                try:
                    return await getattr(deps.llm, role)(brief, tools), "llm"
                except Exception as error:  # noqa: BLE001 - a role that fails falls back to its scripted stand-in
                    timeline.emit(
                        "brain.agent.fallback", state["incident_id"],
                        {"role": role, "error": f"{type(error).__name__}: {str(error)[:300]}", "using": "scripted stand-in"},
                        state.get("trace_id"),
                    )
            return await getattr(deps.scripted, role)(brief, tools), "scripted"
        finally:
            tools.usage.setdefault(role, {})["seconds"] = round(time.monotonic() - started, 2)

    def incident_brief(incident: Incident) -> dict[str, Any]:
        brief = {"incident_id": incident.incident_id, "type": incident.type, "zone_id": incident.zone_id}
        if deps.relative_times:
            brief["seconds_since_incident"] = max(int((clock.current().now() - incident.occurred_at).total_seconds()), 0)
        else:
            brief["occurred_at"] = incident.occurred_at.isoformat()
        return {**brief, "evidence": incident.evidence}

    def alert_zones_allowed(incident: Incident) -> list[str]:
        """Alerts go only to the incident's own zone, only for violent crime, only if the Twin can send them."""
        if "broadcast_alert" not in deps.capabilities or "broadcast_alert" not in manifest.actuators:
            return []
        for reading_id in incident.evidence:
            reading = store.reading(reading_id)
            if reading and reading.type == "cctv_anomaly":
                if CctvAnomaly.model_validate(reading.value).anomaly_type in deps.policy.tactics.alert_anomaly_types:
                    return [incident.zone_id]
        return []

    async def analyst(state: TeamState, config: RunnableConfig) -> dict[str, Any]:
        incident, tools = deps.incidents[state["incident_id"]], toolbox(state, config)
        assessment = Assessment.model_validate(state["assessment"])
        brief = {
            "incident": incident_brief(incident),
            "entity_id": assessment.entity_id,
            "pursuit_already_dispatched": state["reason"] != "ambiguous",
            "assessment": state["assessment"],  # the rule engine's score, features and evidence
        }
        case, mode = await run_role("analyst", brief, tools, state)
        cited, supported, problems = verify_case(case, assessment, tools)
        case = case.model_copy(update={"cited_reading_ids": cited})
        if case.recommendation == "pursue" and not supported:
            case = case.model_copy(update={"recommendation": "watch"})
        timeline.emit(
            "brain.case.reviewed", incident.incident_id,
            {"entity_id": assessment.entity_id, "recommendation": case.recommendation, "confidence": case.confidence,
             "summary": case.summary, "concerns": case.concerns, "cited": cited, "verifier": problems, "mode": mode,
             "usage": _tokens(tools, "analyst")},
            state.get("trace_id"), timing=_timing(tools, "analyst"),
        )
        return {
            "case_file": case.model_dump(mode="json"),
            "pursue": state["reason"] == "ambiguous" and case.recommendation == "pursue",
            "modes": {"analyst": mode}, "revision": 0, "feedback": [],
        }

    def after_analyst(state: TeamState) -> str:
        return "tactician" if state["case_file"]["recommendation"] == "pursue" else END

    async def tactician(state: TeamState, config: RunnableConfig) -> dict[str, Any]:
        incident, tools = open_incident(state), toolbox(state, config)
        zone, heading = _position(store, state["entity_id"], incident)
        brief = {
            "incident": incident_brief(incident), "entity_id": state["entity_id"],
            "current_zone": zone, "heading_zone_id": heading, "case_file": state["case_file"],
            "pursuit_already_dispatched": state["reason"] != "ambiguous",
            "capabilities": sorted(deps.capabilities), "alert_zones_allowed": alert_zones_allowed(incident),
            "units_spare": max(units_free(store, kind) - deps.policy.tactics.reserve_units, 0),
            **({"feedback": state["feedback"]} if state.get("feedback") else {}),
        }
        options, mode = await run_role("tactician", brief, tools, state)
        timeline.emit(
            "brain.options.prepared", incident.incident_id,
            {"entity_id": state["entity_id"], "mode": mode,
             "options": [{"name": o.name, "contain_zones": o.contain_zones, "alert_zones": o.alert_zones, "rationale": o.rationale} for o in options.options],
             "tools_used": [call["tool"] for call in tools.calls if call["tool"].startswith("geo.")],
             "usage": _tokens(tools, "tactician")},
            state.get("trace_id"), timing=_timing(tools, "tactician"),
        )
        return {"options": [o.model_dump(mode="json") for o in options.options], "planned_from": zone,
                "modes": {"tactician": mode}}

    async def chief(state: TeamState, config: RunnableConfig) -> dict[str, Any]:
        incident, tools = open_incident(state), toolbox(state, config)
        questions = [f"{incident.type} suspect: {o['name'].replace('-', ' ')}. {o['rationale']}" for o in state["options"]]
        questions.append("how many units must stay in reserve")
        questions.append(f"case confidence is {state['case_file']['confidence']}: " + "; ".join(state["case_file"]["concerns"]))
        if any(o["alert_zones"] for o in state["options"]):
            questions.append("public alert near a violent crime")
        playbook = await tools.playbook_for(questions)
        optimum = {}
        if deps.policy.optimiser.perimeter == "on":  # the fewest units that would hold, computed in code, so the model reads it whether or not it asks
            suspect_zone, _ = _position(store, state["entity_id"], incident)
            found = await tools.solver_perimeter(suspect_zone)
            optimum = {"perimeter_optimum": {k: found[k] for k in ("feasible", "zones", "from_stations", "seconds_ahead_of_suspect", "reason")}}
        brief = {
            "incident": incident_brief(incident), "entity_id": state["entity_id"],
            "case_file": state["case_file"], "options": state["options"], **optimum,
            "units_available": units_free(store, kind), "reserve_units": deps.policy.tactics.reserve_units,
            "playbook": playbook,
            **({"feedback": state["feedback"]} if state.get("feedback") else {}),
        }
        decision, mode = await run_role("chief", brief, tools, state)
        return {"decision": decision.model_dump(mode="json"), "modes": {"chief": mode}}

    async def verify(state: TeamState, config: RunnableConfig) -> dict[str, Any]:
        incident, tools = open_incident(state), toolbox(state, config)
        decision = ChiefDecision.model_validate(state["decision"])
        plan = verify_plan(
            [TacticalOption.model_validate(o) for o in state["options"]], decision, tools,
            units_available=units_free(store, kind), reserve_units=deps.policy.tactics.reserve_units,
            alert_zones_allowed=alert_zones_allowed(incident),
        )
        revision = state.get("revision", 0)
        if plan.ok and plan.contain_zones and deps.policy.optimiser.perimeter == "on":
            from brain.engines.perimeter import check_plan

            suspect_zone, _ = _position(store, state["entity_id"], incident)
            checked = check_plan(store, suspect_zone, plan.contain_zones, sigma=deps.policy.optimiser.perimeter_sigma)
            timeline.emit("brain.perimeter.checked", incident.incident_id, {"entity_id": state["entity_id"], **checked}, state.get("trace_id"))
            # A critic, not a veto: a plan that holds more units than a solver says are needed goes back to the team once; the second time it stands.
            if checked["solver_gap"] is not None and checked["solver_gap"] > deps.policy.optimiser.perimeter_slack and revision < deps.max_revisions:
                plan = plan.model_copy(update={"ok": False, "problems": [*plan.problems, f"the perimeter uses {checked['team_units']} units; a solver says {checked['optimal_units']} would hold "
                                                                                        f"({', '.join(checked['solver_zones'])}); keep the rest in reserve or say why they are needed"]})
        timeline.emit(
            "brain.plan.verified" if plan.ok else "brain.plan.rejected", incident.incident_id,
            {"entity_id": state["entity_id"], "option": plan.option or decision.chosen_option,
             "contain_zones": plan.contain_zones, "alert_zones": plan.alert_zones,
             "playbook": plan.playbook_citations,
             "playbook_titles": {item: deps.kb.title(item) for item in plan.playbook_citations},
             "retrieval": [call["trace"] for call in tools.calls if call["tool"] == "kb.search" and "trace" in call],
             "justification": decision.justification,
             "problems": plan.problems, "revision": revision, "modes": state.get("modes", {}),
             "usage": _tokens(tools, "chief")},
            state.get("trace_id"), timing=_timing(tools, "chief"),
        )
        if plan.ok:
            return {"plan": plan.model_dump(mode="json")}
        return {"plan": plan.model_dump(mode="json"), "feedback": plan.problems, "revision": revision + 1}

    def after_verify(state: TeamState) -> str:
        if state["plan"]["ok"]:
            return "propose"
        if state["revision"] <= deps.max_revisions:
            return "tactician"
        # No acceptable plan. A pursuit the Analyst justified still goes ahead on its own.
        return "propose" if state.get("pursue") else END

    async def propose(state: TeamState) -> dict[str, Any]:
        incident = open_incident(state)
        trace_id = state.get("trace_id")
        assessment = Assessment.model_validate(state["assessment"])
        case, plan = CaseFile.model_validate(state["case_file"]), VerifiedPlan.model_validate(state["plan"])
        if state["reason"] == "ambiguous":
            # The rules did not find enough; the team acts only on what the Analyst cited and the verifier confirmed.
            assessment = assessment.model_copy(update={"evidence_reading_ids": case.cited_reading_ids})
        entity, (zone, _) = state["entity_id"], _position(store, state["entity_id"], incident)
        cites = plan.playbook_citations
        reserved: dict[str, int] = {}
        wanted: list[tuple[str, dict[str, Any], str, list[str]]] = []
        if state.get("pursue"):
            wanted.append((
                "dispatch_unit",
                {"unit_type": "police", "zone_id": zone, "incident_id": incident.incident_id, "mode": "pursuit", "target_id": entity},
                f"Analyst ({case.confidence} confidence): {case.summary}", ["POL-PB-001"] if deps.kb.has("POL-PB-001") else [],
            ))
        for contain_zone in plan.contain_zones:
            wanted.append((
                "dispatch_unit",
                {"unit_type": "police", "zone_id": contain_zone, "incident_id": incident.incident_id, "mode": "contain", "target_id": entity},
                f"Perimeter for {entity} ({plan.option}). {plan.justification}", cites,
            ))
        for alert_zone in plan.alert_zones:
            name = store.zones.nodes[alert_zone].get("name", alert_zone)
            tactics = deps.policy.tactics
            wanted.append((
                "broadcast_alert",
                {"message": tactics.alert_message.format(zone=name), "channel": tactics.alert_channel, "zone_id": alert_zone},
                f"Public alert for {incident.incident_id} ({plan.option}). {plan.justification}", cites,
            ))

        proposals = []
        for action, params, justification, knowledge in wanted:
            proposal = make_proposal(act, incident, assessment.evidence_reading_ids, action, params, tier="deliberate",
                                     justification=justification, knowledge_citations=knowledge, reserved=reserved,
                                     direct_reading_id=assessment.direct_reading_id)
            if proposal is not None:
                proposals.append(proposal.model_dump(mode="json"))
            else:
                timeline.emit(
                    "brain.action.blocked", incident.incident_id,
                    {"stage": "team", "check": "resources", "would_have": action, "params": params,
                     "reason": "no station has a unit available"},
                    trace_id,
                )
        return {"proposals": proposals}

    async def gate(state: TeamState) -> dict[str, Any]:
        approvals, new_blocked = await gate_proposals(act, state["proposals"], state.get("blocked", []), state.get("trace_id"))
        return {"approvals": approvals, "blocked": new_blocked}

    async def actuate(state: TeamState) -> dict[str, Any]:
        actions = await execute_approvals(act, state["approvals"], state.get("trace_id"))
        held = [
            a["params"]["zone_id"] for a in actions
            if a["params"].get("mode") == "contain" and a["result"].get("status") in ("dispatched", "duplicate")
        ]
        if held:
            # Remembered so the reflex tier can tell when the suspect is seen somewhere this plan does not cover.
            zone = state.get("planned_from") or deps.incidents[state["incident_id"]].zone_id
            act.plans[(state["incident_id"], state["entity_id"])] = {
                "option": state["plan"].get("option"), "zone": zone, "contain_zones": held,
                "inside": sorted(geo.expected_zones(store, zone, held)),
            }
        return {"actions": actions}

    graph = StateGraph(TeamState)
    for name, node in (("analyst", analyst), ("tactician", tactician), ("chief", chief), ("verify", verify),
                       ("propose", propose), ("gate", gate), ("actuate", actuate)):
        graph.add_node(name, node)
    graph.add_edge(START, "analyst")
    graph.add_conditional_edges("analyst", after_analyst, {"tactician": "tactician", END: END})
    graph.add_edge("tactician", "chief")
    graph.add_edge("chief", "verify")
    graph.add_conditional_edges("verify", after_verify, {"propose": "propose", "tactician": "tactician", END: END})
    graph.add_edge("propose", "gate")
    graph.add_edge("gate", "actuate")
    graph.add_edge("actuate", END)
    return graph.compile(checkpointer=InMemorySaver())


TEAM_TOOLS = {"analyst": ["graph.context", "episodes.similar", "kb.graph_search", "solver.plan_allocation", "solver.perimeter", "graph.cascade", "math.time_to_threshold"]}


def role_tools(manifest: Manifest, models: ModelsConfig) -> dict[str, list[str]]:
    """The read-only tools each role has: the pack's own, and (with `knowledge.team_tools`) the Analyst's three more."""
    tools = {name: list(spec.tools) for name, spec in manifest.agents.items()}
    if models.knowledge.team_tools:
        for role, extra in TEAM_TOOLS.items():
            if role in tools:
                tools[role] += [name for name in extra if name not in tools[role]]
    return tools


def _cassette(models: ModelsConfig) -> Any:  # also used by the department desks
    team = models.team
    if team.cassette == "off":
        return None
    if not team.cassette_path:
        raise ValueError("team.cassette is on but team.cassette_path is not set")
    from brain.cassette import Cassette

    return Cassette(team.cassette_path, team.cassette)


def make_crews(manifest: Manifest, policy: Policy, models: ModelsConfig) -> tuple[ScriptedCrew, LLMCrew | None]:
    scripted = ScriptedCrew(policy, manifest.facility_type or "")
    if not models.team.llm:
        return scripted, None
    llm = LLMCrew(
        {name: models.roles[spec.model] for name, spec in manifest.agents.items()},
        role_tools(manifest, models),
        models.team.structured_output,
        role_options={name: models.options_for(spec.model) for name, spec in manifest.agents.items()},
        cassette=_cassette(models),
    )
    return scripted, llm


class Deliberations:
    """Runs department teams as background tasks so the reading loop never waits on them."""

    def __init__(self, team_graph: Any, deps: TeamDeps, timeline: Timeline, budget_s: float, on_pursuit: Any = None,
                 on_finished: Any = None) -> None:
        self._graph = team_graph
        self._deps = deps
        self._timeline = timeline
        self._budget_s = budget_s
        self._on_pursuit = on_pursuit
        self._on_finished = on_finished
        self._tasks: set[asyncio.Task[None]] = set()
        self._taken: set[tuple[Any, ...]] = set()
        self._done: set[tuple[Any, ...]] = set()
        self._new = False
        # A repeatable run does not let the team race the reflex path: it is held until the reflex path has finished, then run to the end.
        self._deferred: list[tuple[Any, ...]] = []

    def snapshot(self) -> dict[str, Any]:
        """Only finished deliberations: one cut short by a restart must be asked for again."""
        return {"done": [list(key) for key in sorted(self._done, key=str)]}

    def restore(self, saved: dict[str, Any]) -> None:
        self._done = {tuple(key) for key in saved.get("done", [])}
        self._taken = set(self._done)

    def finished(self, incident_id: str, entity_id: str, reason: str) -> bool:
        return any(key[:3] == (incident_id, entity_id, reason) for key in self._done)

    def request(self, incident_id: str, entity_id: str, reason: str, assessment: dict[str, Any], trace_id: str | None) -> None:
        # A plan is made once per suspect, and once more for each zone they outrun a perimeter to.
        # An ambiguous case is reopened only when its evidence has grown.
        if reason in ("ambiguous", "desk"):  # reopened only when its evidence has grown (a desk: when a new independent source joins)
            evidence: Any = len(assessment.get("evidence_reading_ids", []))
        else:
            evidence = assessment.get("last_zone_id") if reason == "replan" else 0
        key = (incident_id, entity_id, reason, evidence)
        if key in self._taken:
            return
        self._taken.add(key)
        self._new = True
        if clock.current().deterministic:
            self._deferred.append((incident_id, entity_id, reason, assessment, trace_id, evidence))
            return
        task = asyncio.create_task(self._run(incident_id, entity_id, reason, assessment, trace_id, evidence))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(self, incident_id: str, entity_id: str, reason: str, assessment: dict[str, Any],
                   trace_id: str | None, evidence: Any) -> None:
        thread_id = f"{incident_id}/{entity_id}/{reason}/{evidence}"
        self._timeline.emit("brain.deliberation.started", incident_id, {
            "entity_id": entity_id, "reason": reason, "budget_s": self._budget_s,
            "crew": "llm" if self._deps.llm is not None else "scripted",
        }, trace_id)
        outcome: dict[str, Any] = {"entity_id": entity_id, "reason": reason}
        try:
            state = await asyncio.wait_for(
                self._graph.ainvoke(
                    {"incident_id": incident_id, "entity_id": entity_id, "reason": reason,
                     "assessment": assessment, "trace_id": trace_id or ""},
                    config={"configurable": {"thread_id": thread_id}, "recursion_limit": 40},
                ),
                self._budget_s,
            )
            actions = state.get("actions", [])
            outcome.update(status="completed", actions=len(actions), modes=state.get("modes", {}),
                           recommendation=state.get("case_file", {}).get("recommendation"))
            for action in actions:
                params = action["params"]
                if params.get("mode") == "pursuit" and action["result"].get("status") == "dispatched" and self._on_pursuit:
                    await self._on_pursuit(incident_id, params["target_id"], params["zone_id"])
        except TimeoutError:
            outcome.update(status="timeout", note="the reflex tier's decision stands")
        except IncidentClosed:
            outcome.update(status="abandoned", note="the incident closed before the team finished")
        except Exception as error:  # noqa: BLE001 - a failed team run is recorded; the reading loop never waits on it
            outcome.update(status="failed", error=f"{type(error).__name__}: {str(error)[:300]}")
        finally:
            self._deps.toolboxes.pop(thread_id, None)
        self._done.add((incident_id, entity_id, reason, evidence))
        self._timeline.emit("brain.deliberation.finished", incident_id, outcome, trace_id)
        if self._on_finished is not None:
            await self._on_finished()

    async def _run_deferred(self) -> None:
        while self._deferred:
            await self._run(*self._deferred.pop(0))

    async def head_start(self, seconds: float) -> None:
        """Give deliberations requested since the last call up to `seconds` to finish. Never longer."""
        await self._run_deferred()
        if not self._new or seconds <= 0 or not self._tasks:
            self._new = False
            return
        self._new = False
        await asyncio.wait(list(self._tasks), timeout=seconds)

    async def drain(self) -> bool:
        """Wait for running deliberations. Returns whether there was anything to wait for."""
        held = bool(self._deferred)
        await self._run_deferred()
        if not self._tasks:
            return held
        await asyncio.gather(*list(self._tasks), return_exceptions=True)
        return True
