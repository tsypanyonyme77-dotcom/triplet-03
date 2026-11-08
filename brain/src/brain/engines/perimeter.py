"""The fewest units that seal a suspect in, each held zone reached before the suspect gets there.

The old cut (`geo.containment_cut`) finds the smallest set of zones that separates the suspect from every exit, but not whether a unit can get
there in time, and not which station sends it. This chooses both together with CP-SAT: a zone is held by one unit from one station;
a unit may hold a zone only if it arrives (hops times `unit_hop_s`, plus `margin_s`) before the suspect could (hops times `suspect_hop_s`);
the held zones must cut every path from the suspect's zone to an exit; fewest units first, then the earliest arrivals. When no perimeter is
possible it says so and names the zones it would have needed that no unit reaches in time.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import networkx as nx
from ortools.sat.python import cp_model

from brain.engines import Certificate, inputs_hash

UNIT_HOP_S = 60.0
SUSPECT_HOP_S = 90.0
MARGIN_S = 15.0


@dataclass
class Perimeter:
    zones: list[str]
    assignment: dict[str, str]                 # held zone -> station id
    arrival_slack_s: dict[str, float]          # held zone -> seconds the unit arrives before the suspect
    unit_eta_s: dict[str, float] = field(default_factory=dict)
    suspect_eta_s: dict[str, float] = field(default_factory=dict)
    units_used: int = 0
    certificate: Certificate | None = None
    reason: str = ""

    @property
    def feasible(self) -> bool:
        return self.certificate is not None and self.certificate.status in ("optimal", "feasible")


def _times(store: Any, suspect_zone: str, stations: list[dict[str, Any]], unit_hop_s: float, suspect_hop_s: float) -> tuple[dict[str, float], dict[tuple[str, str], float]]:
    graph = store.zones
    from_suspect = nx.single_source_shortest_path_length(graph, suspect_zone)
    suspect = {z: d * suspect_hop_s for z, d in from_suspect.items()}
    unit: dict[tuple[str, str], float] = {}
    for st in stations:
        for z, d in nx.single_source_shortest_path_length(graph, st["zone_id"]).items():
            unit[(st["id"], z)] = d * unit_hop_s
    return suspect, unit


def perimeter(store: Any, suspect_zone: str, stations: list[dict[str, Any]] | None = None, *, unit_hop_s: float = UNIT_HOP_S,
              suspect_hop_s: float = SUSPECT_HOP_S, margin_s: float = MARGIN_S, time_limit_ms: int = 200) -> Perimeter:
    started = time.perf_counter()
    graph = store.zones
    stations = [s for s in (stations if stations is not None else store.facilities("police_station")) if not s.get("quarantined") and s.get("available", s.get("units", 0)) > 0]
    problem = {"z": suspect_zone, "st": sorted((s["id"], s["zone_id"], s.get("available", s.get("units", 0))) for s in stations), "x": sorted(store.exits),
               "t": [unit_hop_s, suspect_hop_s, margin_s]}
    if suspect_zone not in graph:
        return Perimeter([], {}, {}, certificate=Certificate(engine="perimeter", status="infeasible", inputs_hash=inputs_hash(problem)), reason=f"{suspect_zone} is not in the topology")
    suspect_eta, unit_eta = _times(store, suspect_zone, stations, unit_hop_s, suspect_hop_s)
    zones = sorted(graph.nodes)

    def solve(timing: bool) -> tuple[Any, dict[Any, Any], dict[str, Any], dict[Any, Any]]:
        model = cp_model.CpModel()
        x = {}
        for st in stations:
            for z in zones:
                if z == suspect_zone or (st["id"], z) not in unit_eta:
                    continue
                if timing and unit_eta[(st["id"], z)] + margin_s > suspect_eta.get(z, float("inf")):
                    continue
                x[(st["id"], z)] = model.new_bool_var(f"x_{st['id']}_{z}")
        held = {z: model.new_bool_var(f"y_{z}") for z in zones}
        reach = {z: model.new_bool_var(f"r_{z}") for z in zones}
        for z in zones:
            sources = [v for (s, zz), v in x.items() if zz == z]
            model.add(sum(sources) == held[z]) if sources else model.add(held[z] == 0)
        for st in stations:
            model.add(sum(v for (s, z), v in x.items() if s == st["id"]) <= st.get("available", st.get("units", 0)))
        model.add(reach[suspect_zone] == 1)
        for u, v in graph.edges:
            for a, b in ((u, v), (v, u)):
                model.add_bool_or([reach[a].negated(), held[b], reach[b]])  # reached a, b not held => reached b
        for e in store.exits:
            if e in reach:
                model.add(reach[e] == 0)
        model.minimize(sum(10_000 * v for v in held.values()) + sum(round(unit_eta[k]) * v for k, v in x.items()))
        solver = cp_model.CpSolver()
        solver.parameters.num_workers, solver.parameters.random_seed, solver.parameters.max_time_in_seconds = 1, 1, time_limit_ms / 1000
        return solver.solve(model), x, held, solver

    status, x, held, solver = solve(timing=True)
    elapsed = (time.perf_counter() - started) * 1000
    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        assignment = {z: s for (s, z), v in x.items() if solver.value(v)}
        cut = sorted(assignment)
        return Perimeter(cut, dict(sorted(assignment.items())), {z: round(suspect_eta[z] - unit_eta[(assignment[z], z)] - margin_s, 1) for z in cut},
                         {z: unit_eta[(assignment[z], z)] for z in cut}, {z: suspect_eta[z] for z in cut}, len(cut),
                         Certificate(engine="perimeter", status="optimal" if status == cp_model.OPTIMAL else "feasible", objective=float(len(cut)),
                                     inputs_hash=inputs_hash(problem), elapsed_ms=round(elapsed, 3)))
    # Not possible in time: what would the cut need if time did not matter, and which of its zones can no unit reach first?
    relaxed, rx, _, rsolver = solve(timing=False)
    miss = ""
    if relaxed in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        needed = sorted({z for (s, z), v in rx.items() if rsolver.value(v)})
        late = [z for z in needed if all(unit_eta.get((st["id"], z), float("inf")) + margin_s > suspect_eta.get(z, float("inf")) for st in stations)]
        miss = f"the nearest miss holds {needed}; no unit reaches {late or needed} before the suspect"
    return Perimeter([], {}, {}, certificate=Certificate(engine="perimeter", status="infeasible", inputs_hash=inputs_hash(problem), elapsed_ms=round(elapsed, 3)),
                     reason=miss or "no set of zones separates the suspect from every exit with the units available")


def check_plan(store: Any, suspect_zone: str, held_zones: list[str], *, sigma: float = 0.3) -> dict[str, Any]:
    """Compare a team's perimeter with the solver's: how many units it uses against the fewest that would do, and the chance the solver's holds."""
    from brain.engines.robust import robust

    optimal = perimeter(store, suspect_zone)
    stations = [s for s in store.facilities("police_station") if not s.get("quarantined") and s.get("available", s.get("units", 0)) > 0]
    suspect_eta, unit_eta = _times(store, suspect_zone, stations, UNIT_HOP_S, SUSPECT_HOP_S) if suspect_zone in store.zones else ({}, {})
    # a held zone is late when no station can reach it before the suspect could (the team's cut may be smaller than the timed optimum for this reason)
    late = sorted(z for z in held_zones if all(unit_eta.get((s["id"], z), float("inf")) + MARGIN_S > suspect_eta.get(z, float("inf")) for s in stations))
    return {
        "team_zones_late": late,
        "suspect_zone": suspect_zone, "team_zones": sorted(held_zones), "team_units": len(held_zones), "feasible": optimal.feasible,
        "optimal_units": optimal.units_used if optimal.feasible else None, "solver_gap": len(held_zones) - optimal.units_used if optimal.feasible else None,
        "solver_zones": optimal.zones, "min_slack_s": min(optimal.arrival_slack_s.values(), default=None),
        "robust_p": robust(optimal, sigma=sigma) if optimal.feasible else None, "sigma": sigma, "reason": optimal.reason,
        "status": optimal.certificate.status if optimal.certificate else None, "inputs_hash": optimal.certificate.inputs_hash if optimal.certificate else None,
    }
