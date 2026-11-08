"""The planning supervisor: a LangGraph graph that lets a solver and the team answer an incident at their own speed and reconciles them.

`assemble` gathers the facts and fans out. The solver's answer goes through the gate at once, inside its own node, so a slow or absent team
never delays the first response. The team's plan arrives later and is reconciled: a plan the verifier rejects is dropped; a feasible plan
no worse than the solver's (within a tolerance) adds its unsent actions; otherwise the solver's stand and the team's plan is recorded as
dominated, with its gap. A call that needs a person pauses at `approve` (a LangGraph interrupt) and resumes when it is answered, even in a
new process: every step is checkpointed in SQLite, one thread per incident. The graph decides nothing itself: the nodes are injected, and
everything it sends goes through the gate.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, TypedDict

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, Send, interrupt


class Plan(TypedDict, total=False):
    actions: list[dict[str, Any]]  # ProposedAction dumps
    cost: float | None             # the plan's objective, in the solver's units (lower is better)
    valid: bool                    # did the verifier accept it (always true for a solver)


class PlanState(TypedDict, total=False):
    incident_id: str
    facts: dict[str, Any]
    solver: Plan
    team: Plan | None
    sent: list[dict[str, Any]]       # what the gate sent from the solver's plan
    merged: list[dict[str, Any]]     # the team's extra actions to send
    stood: str                       # solver | team
    gap: float | None
    approvals: list[str]
    result: list[dict[str, Any]]


def key_of(action: dict[str, Any]) -> str:
    return json.dumps([action.get("action"), action.get("actuator_id"), action.get("params")], sort_keys=True, default=str)


def reconcile(solver: Plan, team: Plan | None, sent: list[dict[str, Any]], tolerance: float = 0.0) -> dict[str, Any]:
    """Which plan stands, what the team adds, and how far the team's plan was from the solver's."""
    if team is None or not team.get("valid", False):
        return {"stood": "solver", "merged": [], "gap": None, "why": "no team plan" if team is None else "the verifier rejected the team plan"}
    gap = None if solver.get("cost") is None or team.get("cost") is None else round(team["cost"] - solver["cost"], 3)
    if gap is None or gap <= tolerance:
        done = {key_of(a) for a in sent}
        return {"stood": "team", "merged": [a for a in team.get("actions", []) if key_of(a) not in done], "gap": gap, "why": "feasible and no worse than the solver"}
    return {"stood": "solver", "merged": [], "gap": gap, "why": "dominated by the solver"}


@dataclass
class PlanNodes:
    solve: Callable[[PlanState], Awaitable[Plan]]
    gate: Callable[[list[dict[str, Any]], str], Awaitable[list[dict[str, Any]]]]  # gate and send; returns one record per call that was sent
    deliberate: Callable[[PlanState], Awaitable[Plan | None]] | None = None
    needs_person: Callable[[list[dict[str, Any]]], list[str]] = lambda actions: []  # ids of calls that wait for a signed approval
    emit: Callable[[str, str, dict[str, Any]], None] = lambda type, subject, data: None
    tolerance: float = 0.0


def build(nodes: PlanNodes, checkpointer: Any):
    async def assemble(state: PlanState) -> Command:
        goto = [Send("solve", state)] + ([Send("deliberate", state)] if nodes.deliberate else [])
        return Command(goto=goto)

    async def solve(state: PlanState) -> dict[str, Any]:
        # Gated inside the same step as the solving: a graph step waits for every branch, so a separate node would wait for the team.
        plan = await nodes.solve(state)
        return {"solver": plan, "sent": await nodes.gate(plan.get("actions", []), state["incident_id"])}

    async def deliberate(state: PlanState) -> dict[str, Any]:
        return {"team": await nodes.deliberate(state)}

    async def reconcile_node(state: PlanState) -> dict[str, Any]:
        outcome = reconcile(state["solver"], state.get("team"), state.get("sent", []), nodes.tolerance)
        nodes.emit("brain.plan.reconciled", state["incident_id"], {"stood": outcome["stood"], "gap": outcome["gap"], "why": outcome["why"],
                                                                     "solver_cost": state["solver"].get("cost"), "team_cost": (state.get("team") or {}).get("cost"), "added": len(outcome["merged"])})
        return {"stood": outcome["stood"], "merged": outcome["merged"], "gap": outcome["gap"]}

    async def approve(state: PlanState) -> dict[str, Any]:
        waiting = nodes.needs_person(state.get("merged", []))
        if not waiting:
            return {"approvals": []}
        answer = interrupt({"pending": waiting, "incident_id": state["incident_id"]})  # resumed by Command(resume=...)
        granted = [w for w in waiting if w in (answer or {}).get("granted", [])]
        refused = set(waiting) - set(granted)
        return {"approvals": granted, "merged": [a for a in state["merged"] if a.get("actuator_id") not in refused]}

    async def gate_team(state: PlanState) -> dict[str, Any]:
        return {"result": await nodes.gate(state.get("merged", []), state["incident_id"]) if state.get("merged") else []}

    graph = StateGraph(PlanState)
    graph.add_node("assemble", assemble, destinations=("solve", "deliberate"))
    graph.add_node("solve", solve)
    graph.add_node("deliberate", deliberate)
    graph.add_node("reconcile", reconcile_node)
    graph.add_node("approve", approve)
    graph.add_node("gate_team", gate_team)
    graph.add_edge(START, "assemble")
    graph.add_edge(["solve", "deliberate"] if nodes.deliberate else ["solve"], "reconcile")
    graph.add_edge("reconcile", "approve")
    graph.add_edge("approve", "gate_team")
    graph.add_edge("gate_team", END)
    return graph.compile(checkpointer=checkpointer)


async def open_checkpointer(path: str) -> AsyncSqliteSaver:
    import aiosqlite

    return AsyncSqliteSaver(await aiosqlite.connect(path))


async def prune(saver: AsyncSqliteSaver, limit: int) -> int:
    """Keep the newest `limit` checkpoints (a checkpoint table that only grows is a slow leak). Returns how many were removed."""
    async with saver.conn.execute("SELECT COUNT(*) FROM checkpoints") as cursor:
        (count,) = await cursor.fetchone()
    if count <= limit:
        return 0
    await saver.conn.execute("DELETE FROM writes WHERE rowid IN (SELECT w.rowid FROM writes w LEFT JOIN checkpoints c ON c.thread_id = w.thread_id AND c.checkpoint_ns = w.checkpoint_ns AND c.checkpoint_id = w.checkpoint_id WHERE c.checkpoint_id IS NULL)")
    await saver.conn.execute("DELETE FROM checkpoints WHERE rowid IN (SELECT rowid FROM checkpoints ORDER BY checkpoint_id ASC LIMIT ?)", (count - limit,))
    await saver.conn.commit()
    return count - limit
