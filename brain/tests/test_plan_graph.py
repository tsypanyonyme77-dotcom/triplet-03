"""The planning supervisor: the solver goes to the gate first, the team is reconciled when it arrives, a person's approval pauses and resumes it."""

import asyncio

from langgraph.types import Command

from brain.plan import PlanNodes, build, open_checkpointer, prune, reconcile

SAFE = {"action": "dispatch_unit", "actuator_id": "ps-1", "params": {"zone_id": "z1"}}
VALVE = {"action": "set_valve_state", "actuator_id": "valve-01", "params": {"state": "closed"}}


def config(incident="inc-1"):
    return {"configurable": {"thread_id": f"{incident}:plan"}}


async def run(nodes, path=":memory:", incident="inc-1"):
    saver = await open_checkpointer(path)
    graph = build(nodes, saver)
    return graph, saver, await graph.ainvoke({"incident_id": incident, "facts": {}}, config(incident))


def recorder():
    sent: list[list] = []

    async def gate(actions, incident):
        sent.append(list(actions))
        return [dict(a) for a in actions]
    return sent, gate


async def test_the_solver_proposals_reach_the_gate_before_the_team_has_answered():
    sent, gate = recorder()
    gated = asyncio.Event()

    async def solve(state):
        return {"actions": [SAFE], "cost": 4.0, "valid": True}

    async def team(state):
        await asyncio.wait_for(gated.wait(), 2)  # the team can only finish after the solver's plan has been gated
        return {"actions": [], "cost": 9.0, "valid": True}

    async def gate_and_signal(actions, incident):
        gated.set()
        return await gate(actions, incident)

    _, _, state = await run(PlanNodes(solve, gate_and_signal, team))

    assert sent[0] == [SAFE] and state["stood"] == "solver"


async def test_a_team_plan_that_fails_verify_plan_never_replaces_the_solver():
    sent, gate = recorder()

    async def solve(state):
        return {"actions": [SAFE], "cost": 4.0, "valid": True}

    async def team(state):
        return {"actions": [VALVE], "cost": 1.0, "valid": False}

    _, _, state = await run(PlanNodes(solve, gate, team))

    assert state["stood"] == "solver" and [VALVE] not in sent


async def test_a_better_feasible_team_plan_replaces_unsent_solver_actions_only():
    sent, gate = recorder()
    extra = {"action": "set_signal_phase", "actuator_id": "signal-1", "params": {"phase": "green"}}

    async def solve(state):
        return {"actions": [SAFE], "cost": 4.0, "valid": True}

    async def team(state):
        return {"actions": [SAFE, extra], "cost": 3.0, "valid": True}

    _, _, state = await run(PlanNodes(solve, gate, team))

    assert state["stood"] == "team" and sent == [[SAFE], [extra]]  # the unit already sent is not sent again


async def test_a_dominated_team_plan_is_recorded_with_its_gap():
    events = []

    async def solve(state):
        return {"actions": [SAFE], "cost": 4.0, "valid": True}

    async def team(state):
        return {"actions": [], "cost": 7.5, "valid": True}

    _, _, state = await run(PlanNodes(solve, recorder()[1], team, emit=lambda t, s, d: events.append((t, d))))

    assert state["gap"] == 3.5 and events[0][0] == "brain.plan.reconciled" and events[0][1]["why"] == "dominated by the solver"


async def test_a_high_impact_action_pauses_at_approve_and_resumes_on_a_grant():
    sent, gate = recorder()

    async def solve(state):
        return {"actions": [], "cost": 4.0, "valid": True}

    async def team(state):
        return {"actions": [VALVE], "cost": 3.0, "valid": True}

    nodes = PlanNodes(solve, gate, team, needs_person=lambda actions: [a["actuator_id"] for a in actions if a["action"] == "set_valve_state"])
    graph, saver, paused = await run(nodes)
    assert "__interrupt__" in paused and sent == [[]]

    done = await graph.ainvoke(Command(resume={"granted": ["valve-01"]}), config())
    assert sent[-1] == [VALVE] and done["approvals"] == ["valve-01"]


async def test_a_denied_approval_sends_nothing():
    sent, gate = recorder()

    async def solve(state):
        return {"actions": [], "cost": 4.0, "valid": True}

    async def team(state):
        return {"actions": [VALVE], "cost": 3.0, "valid": True}

    nodes = PlanNodes(solve, gate, team, needs_person=lambda actions: ["valve-01"])
    graph, _, _ = await run(nodes)
    await graph.ainvoke(Command(resume={"granted": []}), config())

    assert [VALVE] not in sent


async def test_a_pending_approval_survives_a_restart_and_resumes(tmp_path):
    path = str(tmp_path / "plan.sqlite")
    sent, gate = recorder()

    async def solve(state):
        return {"actions": [], "cost": 4.0, "valid": True}

    async def team(state):
        return {"actions": [VALVE], "cost": 3.0, "valid": True}

    nodes = PlanNodes(solve, gate, team, needs_person=lambda actions: ["valve-01"])
    _, saver, paused = await run(nodes, path)
    assert "__interrupt__" in paused
    await saver.conn.close()  # the process ends

    again = build(nodes, await open_checkpointer(path))  # a new process, the same file
    done = await again.ainvoke(Command(resume={"granted": ["valve-01"]}), config())

    assert sent[-1] == [VALVE] and done["stood"] == "team"


async def test_the_checkpoint_table_is_pruned_to_the_limit():
    sent, gate = recorder()

    async def solve(state):
        return {"actions": [SAFE], "cost": 1.0, "valid": True}

    saver = await open_checkpointer(":memory:")
    graph = build(PlanNodes(solve, gate), saver)
    for n in range(6):
        await graph.ainvoke({"incident_id": f"inc-{n}", "facts": {}}, config(f"inc-{n}"))
    removed = await prune(saver, 10)
    async with saver.conn.execute("SELECT COUNT(*) FROM checkpoints") as cursor:
        (left,) = await cursor.fetchone()

    assert removed > 0 and left == 10


def test_reconcile_with_no_team_keeps_the_solver():
    assert reconcile({"cost": 1.0, "actions": []}, None, [])["stood"] == "solver"
