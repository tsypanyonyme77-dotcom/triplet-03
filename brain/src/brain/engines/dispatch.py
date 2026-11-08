"""Which station sends its unit to which incident, when several incidents want the same units.

Nearest-first answers one incident at a time, so the first to ask takes the only close unit even when a later, more serious incident is
next to the same station. This solves all the open incidents together as a min-cost flow (source to stations, stations to incidents,
incidents to sink; the cost of an arc is hops times severity), so a unit goes where it saves the most, and an incident no unit can reach
costs a large penalty rather than disappearing. The same problem always gives the same answer (integer costs, sorted inputs, one thread).
It only chooses a station: the dispatch is still a `ProposedAction` and the gate still has the last word.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ortools.graph.python import min_cost_flow

from brain.engines import Certificate, inputs_hash

SCALE = 100  # severity is a float; the flow wants integers


@dataclass(frozen=True)
class Demand:
    incident_id: str
    zone_id: str
    severity: float = 1.0


@dataclass(frozen=True)
class Supply:
    station_id: str
    zone_id: str
    spare: int


@dataclass
class DispatchSolution:
    assignment: dict[str, str | None]  # incident id -> station id, or None when no unit can be sent
    certificate: Certificate
    nearest: dict[str, str | None] = field(default_factory=dict)  # what nearest-first would have done, in arrival order
    nearest_cost: float = 0.0

    @property
    def regret_vs_nearest(self) -> float:
        return round(self.nearest_cost - (self.certificate.objective or 0.0), 3)


def _cost(severity: float, hops: int) -> int:
    return round(severity * SCALE) * hops


def nearest_first(demands: list[Demand], supplies: list[Supply], hops: Any, penalty: int) -> tuple[dict[str, str | None], int]:
    """The old rule applied to the same problem, in the order the incidents arrived: the comparison the solver is judged against."""
    spare = {s.station_id: s.spare for s in supplies}
    out: dict[str, str | None] = {}
    total = 0
    for demand in demands:
        options = sorted((hops(s.zone_id, demand.zone_id), s.station_id) for s in supplies if spare[s.station_id] > 0 and hops(s.zone_id, demand.zone_id) is not None)
        if options:
            spare[options[0][1]] -= 1
            out[demand.incident_id] = options[0][1]
            total += _cost(demand.severity, options[0][0])
        else:
            out[demand.incident_id] = None
            total += penalty
    return out, total


def solve_dispatch(demands: list[Demand], supplies: list[Supply], hops: Any, *, unmet_penalty: int = 1000, time_limit_ms: int = 200) -> DispatchSolution:
    """`demands` are in arrival order; `hops(a, b)` is the hop distance or None."""
    started = time.perf_counter()
    stations = sorted(supplies, key=lambda s: s.station_id)
    incidents = sorted(demands, key=lambda d: d.incident_id)
    problem = {"d": [(d.incident_id, d.zone_id, d.severity) for d in incidents], "s": [(s.station_id, s.zone_id, s.spare) for s in stations], "p": unmet_penalty}
    nearest, nearest_obj = nearest_first(demands, supplies, hops, unmet_penalty * SCALE)

    # nodes: 0 source, 1 sink, 2 "unmet", then stations, then incidents
    flow = min_cost_flow.SimpleMinCostFlow()
    first_station, first_incident = 3, 3 + len(stations)
    for i, s in enumerate(stations):
        flow.add_arc_with_capacity_and_unit_cost(0, first_station + i, s.spare, 0)
    flow.add_arc_with_capacity_and_unit_cost(0, 2, len(incidents), 0)
    arcs: dict[int, tuple[str, str]] = {}
    for j, d in enumerate(incidents):
        for i, s in enumerate(stations):
            distance = hops(s.zone_id, d.zone_id)
            if distance is not None and s.spare > 0:
                arcs[flow.add_arc_with_capacity_and_unit_cost(first_station + i, first_incident + j, 1, _cost(d.severity, distance))] = (d.incident_id, s.station_id)
        flow.add_arc_with_capacity_and_unit_cost(2, first_incident + j, 1, unmet_penalty * SCALE)
        flow.add_arc_with_capacity_and_unit_cost(first_incident + j, 1, 1, 0)
    flow.set_node_supply(0, len(incidents))
    flow.set_node_supply(1, -len(incidents))
    status = flow.solve()
    elapsed = (time.perf_counter() - started) * 1000
    if status != flow.OPTIMAL or elapsed > time_limit_ms:
        return DispatchSolution(dict(nearest), Certificate(engine="dispatch", status="timeout" if status == flow.OPTIMAL else "infeasible", inputs_hash=inputs_hash(problem), elapsed_ms=round(elapsed, 3)),
                                nearest, nearest_obj / SCALE)
    assignment: dict[str, str | None] = {d.incident_id: None for d in incidents}
    for arc, (incident_id, station_id) in arcs.items():
        if flow.flow(arc) > 0:
            assignment[incident_id] = station_id
    objective = flow.optimal_cost() / SCALE
    certificate = Certificate(engine="dispatch", status="optimal", objective=objective, bound=objective, gap=0.0, inputs_hash=inputs_hash(problem), elapsed_ms=round(elapsed, 3),
                              slack={s.station_id: float(s.spare - sum(1 for v in assignment.values() if v == s.station_id)) for s in stations})
    return DispatchSolution(assignment, certificate, nearest, nearest_obj / SCALE)


class OptimalChooser:
    """Picks a station for one dispatch by solving every open incident that wants the same kind of unit together.

    Any failure falls back to the nearest station, and the timeline says so."""

    def __init__(self, severity: dict[str, float], time_limit_ms: int = 200, unmet_penalty: int = 1000) -> None:
        self.severity, self.time_limit_ms, self.unmet_penalty = severity, time_limit_ms, unmet_penalty

    @staticmethod
    def _wants(act: Any, incident_type: str, kind: str) -> bool:
        """Does an incident of this type send a unit from a facility of this kind? (A department's `dispatch_unit:ambulance` means hospitals.)"""
        from brain.graph.actuation import UNIT_FACILITY

        for manifest in act.manifests.values():
            if incident_type in manifest.incident_types:
                for name in manifest.actuators:
                    if name.startswith("dispatch_unit") and (UNIT_FACILITY.get(name.partition(":")[2]) or manifest.facility_type) == kind:
                        return True
        return False

    def _demands(self, act: Any, incident: Any, zone_id: str, kind: str) -> list[Demand]:
        severity = lambda i: float(self.severity.get(i.type, 1.0))  # noqa: E731
        waiting = []
        for node, attrs in act.store.g.nodes(data=True):
            other = attrs.get("incident") if node[0] == "incident" else None
            if other is None or other.status != "open" or other.incident_id == incident.incident_id or act.store.units_out(other.incident_id):
                continue
            if self._wants(act, other.type, kind):
                waiting.append(other)
        waiting.sort(key=lambda i: (i.occurred_at, i.incident_id))
        demands = [Demand(i.incident_id, i.zone_id, severity(i)) for i in waiting]
        demands.append(Demand(incident.incident_id, zone_id, severity(incident)))  # the one asking is the newest in the plan
        return sorted(demands, key=lambda d: d.incident_id == incident.incident_id)

    def choose(self, act: Any, incident: Any, zone_id: str, reserved: dict[str, int], kind: str) -> dict[str, Any] | None:
        nearest = act.store.nearest_facility(zone_id, kind, need_unit=True, reserved=reserved)
        try:
            supplies = [Supply(f["id"], f["zone_id"], f["units"] - f["committed"] - reserved.get(f["id"], 0))
                        for f in act.store.facilities(kind) if not f["quarantined"] and f["units"] - f["committed"] - reserved.get(f["id"], 0) > 0]
            demands = self._demands(act, incident, zone_id, kind)
            if len(demands) < 2:
                return nearest  # nothing competes for the units: the nearest station is the optimum, and the old answer stays the answer
            act.timeline.emit("brain.solver.started", incident.incident_id, {"engine": "dispatch", "incidents": [d.incident_id for d in demands], "stations": [s.station_id for s in supplies]})
            solution = solve_dispatch(demands, supplies, act.store.hop_distance, unmet_penalty=self.unmet_penalty, time_limit_ms=self.time_limit_ms)
            certificate = solution.certificate
            if certificate.status != "optimal":
                act.timeline.emit("brain.solver.fallback", incident.incident_id, {"engine": "dispatch", "why": certificate.status, "used": nearest["id"] if nearest else None}, timing={"elapsed_ms": certificate.elapsed_ms})
                return nearest
            chosen = solution.assignment.get(incident.incident_id)
            if solution.regret_vs_nearest <= 0:
                chosen = solution.nearest.get(incident.incident_id)  # a tie, or no gain: never differ from nearest-first without a saving
            act.timeline.emit("brain.solver.solved", incident.incident_id, {
                "engine": "dispatch", "station": chosen, "nearest": solution.nearest.get(incident.incident_id), "objective": certificate.objective,
                "nearest_objective": solution.nearest_cost, "regret_vs_nearest": solution.regret_vs_nearest, "status": certificate.status,
                "inputs_hash": certificate.inputs_hash, "assignment": dict(sorted(solution.assignment.items()))}, timing={"elapsed_ms": certificate.elapsed_ms})
            if chosen is None:
                return nearest
            return next((f for f in act.store.facilities(kind) if f["id"] == chosen), nearest)
        except Exception as error:  # a solver that cannot answer must never stop a dispatch  # noqa: BLE001
            act.timeline.emit("brain.solver.fallback", incident.incident_id, {"engine": "dispatch", "why": type(error).__name__, "used": nearest["id"] if nearest else None})
            return nearest
