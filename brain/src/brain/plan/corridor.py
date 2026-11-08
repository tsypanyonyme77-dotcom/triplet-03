"""Runs the planning supervisor for the emergency corridor: when an ambulance or fire unit is sent, hold the signals green along its way.

Triggered by `Actuation.on_dispatch` after the Twin confirmed a dispatch. The solver node is the corridor engine; its proposals are
`set_signal_phase` calls that go through the gate like any other (cooling gap, allowlist, capability, trust). With `orchestration.planner`
off nothing here exists. The team is not asked: a corridor is a calculation, not a deliberation.
"""

from __future__ import annotations

from typing import Any

from brain.engines.corridor import corridor
from brain.graph.actuation import Actuation, execute_approvals, gate_proposals, make_proposal
from brain.plan import PlanNodes, build, open_checkpointer, prune


class CorridorPlanner:
    def __init__(self, act: Actuation, capabilities: set[str], units: list[str], checkpoint_db: str, max_checkpoints: int) -> None:
        self.act, self.capabilities, self.units = act, capabilities, set(units)
        self.checkpoint_db, self.max_checkpoints = checkpoint_db, max_checkpoints
        self.held_until: dict[str, float] = {}

    def _congestion(self) -> dict[str, float]:
        latest: dict[str, tuple[Any, float]] = {}
        for node, attrs in self.act.store.g.nodes(data=True):
            reading = attrs.get("reading") if node[0] == "reading" else None
            if reading is None or reading.type != "traffic_camera":
                continue
            verdict = self.act.store.verdict_of(reading.reading_id)
            if verdict is None or verdict.status.value != "trusted" or "congestion_score" not in reading.value:
                continue
            if reading.zone_id not in latest or reading.timestamp >= latest[reading.zone_id][0]:
                latest[reading.zone_id] = (reading.timestamp, float(reading.value["congestion_score"]))
        return {zone: score for zone, (_, score) in latest.items()}

    async def _solve(self, state: dict[str, Any]) -> dict[str, Any]:
        facts, store = state["facts"], self.act.store
        now = store.latest_at.timestamp() if store.latest_at else 0.0
        result = corridor(store, facts["origin"], facts["dest"], congestion=self._congestion(), can_signal="set_signal_phase" in self.capabilities,
                          held_until=self.held_until, now_s=now)
        if result is None:
            return {"actions": [], "cost": None, "valid": True}
        incident = store.incident(state["incident_id"])
        actions = []
        for hold in result.signals:
            proposal = make_proposal(
                self.act, incident, incident.evidence, "set_signal_phase", {"intersection_id": hold.intersection_id, "phase": hold.phase, "duration_s": hold.duration_s},
                tier="reflex", actuator_id=hold.intersection_id, manifest=self.act.manifests.get("MOBILITY", self.act.manifest),
                justification=f"Hold {hold.intersection_id} green for {hold.duration_s} s: the {facts['unit_type']} from {facts['origin']} reaches {facts['dest']} "
                              f"in {result.eta_s:.0f} s by {' > '.join(result.path)}, {result.gain_s:.0f} s quicker than the plain path.")
            if proposal is not None:
                actions.append(proposal.model_dump(mode="json"))
                self.held_until[hold.intersection_id] = now + hold.duration_s
        self.act.timeline.emit("brain.corridor.opened", state["incident_id"], {
            "path": result.path, "eta_s": result.eta_s, "plain_eta_s": result.plain_eta_s, "gain_s": result.gain_s, "unit_type": facts["unit_type"],
            "signals": [{"intersection_id": s.intersection_id, "zone_id": s.zone_id, "duration_s": s.duration_s} for s in result.signals],
            "inputs_hash": result.certificate.inputs_hash}, facts.get("trace_id"), timing={"elapsed_ms": result.certificate.elapsed_ms})
        self.act.corridors.append({"incident_id": state["incident_id"], "unit_type": facts["unit_type"], "path": result.path, "eta_s": result.eta_s, "gain_s": result.gain_s,
                                   "signals": [s.intersection_id for s in result.signals]})
        return {"actions": actions, "cost": result.eta_s, "valid": True}

    async def _gate(self, actions: list[dict[str, Any]], incident_id: str) -> list[dict[str, Any]]:
        if not actions:
            return []
        approvals, _ = await gate_proposals(self.act, actions, [], None)
        return await execute_approvals(self.act, approvals, None)

    async def on_dispatch(self, proposal: dict[str, Any], outcome: dict[str, Any], trace_id: str | None) -> None:
        unit_type = proposal["params"].get("unit_type")
        if unit_type not in self.units or outcome.get("status") != "dispatched":
            return
        facility = self.act.store._by_actuator(proposal["actuator_id"])
        incident = self.act.store.incident(proposal["incident_id"])
        if facility is None or incident is None:
            return
        facts = {"origin": facility["zone_id"], "dest": proposal["params"].get("zone_id") or incident.zone_id, "unit_type": unit_type, "trace_id": trace_id}
        # One connection per corridor, closed again: a connection left open keeps its thread, and the process, alive at exit.
        saver = await open_checkpointer(self.checkpoint_db)
        try:
            graph = build(PlanNodes(self._solve, self._gate, emit=self.act.timeline.emit), saver)
            await graph.ainvoke({"incident_id": incident.incident_id, "facts": facts}, {"configurable": {"thread_id": f"{incident.incident_id}:plan:{outcome.get('unit_id')}"}})
            await prune(saver, self.max_checkpoints)
        finally:
            await saver.conn.close()
