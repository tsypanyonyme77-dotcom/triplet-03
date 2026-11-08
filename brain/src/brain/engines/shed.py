"""Which zones to disconnect when the grid is overloaded, so as to lose the least.

Removing at least the excess load over `target_ratio` of capacity is a knapsack: choose zones to disconnect so their loads add up to the
excess, at the lowest total impact (what goes dark, from the cascade analysis). CP-SAT solves it exactly with one thread and a fixed seed,
so the same loads give the same choice. A zone whose loss would darken a hospital is only chosen when no other set will do.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ortools.sat.python import cp_model

from brain.engines import Certificate, inputs_hash

SCALE = 1000  # kW and impact are floats; CP-SAT wants integers


class FeederShedder:
    """Plans a shed for an overload: finds the feeder the overloaded zone is on, reads each zone's latest trusted load, and asks `shed`."""

    def __init__(self, target_ratio: float, time_limit_ms: int = 200) -> None:
        self.target_ratio, self.time_limit_ms = target_ratio, time_limit_ms

    def plan(self, store: Any, zone_id: str) -> tuple[str, Shedding, dict[str, float], dict[str, float]] | None:
        from brain.engines.cascade import cascade, load_dependencies, load_feeders

        feeders = load_feeders(store)
        name = next((n for n, f in sorted(feeders.items()) if zone_id in f["zones"]), None)
        if name is None:
            return None  # not on a known feeder: the caller falls back to the plain rule
        try:
            deps = load_dependencies(store)
        except ValueError:
            deps = {}
        loads: dict[str, tuple[Any, float]] = {}
        for node, attrs in store.g.nodes(data=True):
            reading = attrs.get("reading") if node[0] == "reading" else None
            if reading is None or reading.type != "power_load" or reading.zone_id not in feeders[name]["zones"] or "load_kw" not in reading.value:
                continue
            verdict = store.verdict_of(reading.reading_id)
            if verdict is None or verdict.status.value != "trusted":
                continue
            if reading.zone_id not in loads or reading.timestamp >= loads[reading.zone_id][0]:
                loads[reading.zone_id] = (reading.timestamp, float(reading.value["load_kw"]))
        kw = {z: v for z, (_, v) in loads.items()}
        if not kw:
            return None
        impact = {z: cascade(store, deps, {z}).weight for z in kw}
        return name, shed(kw, feeders[name]["capacity_kw"], self.target_ratio, impact, time_limit_ms=self.time_limit_ms), kw, impact


@dataclass
class Shedding:
    disconnect: list[str]
    load_removed_kw: float
    impact: float
    excess_kw: float
    certificate: Certificate
    reasons: dict[str, str] = field(default_factory=dict)


def shed(loads: dict[str, float], capacity_kw: float, target_ratio: float, impact_of: dict[str, float], *, time_limit_ms: int = 200) -> Shedding:
    started = time.perf_counter()
    zones = sorted(loads)
    excess = sum(loads.values()) - target_ratio * capacity_kw
    problem = {"loads": sorted(loads.items()), "cap": capacity_kw, "ratio": target_ratio, "impact": sorted(impact_of.items())}
    if excess <= 0:
        return Shedding([], 0.0, 0.0, 0.0, Certificate(engine="shed", status="optimal", objective=0.0, bound=0.0, gap=0.0, inputs_hash=inputs_hash(problem)))
    model = cp_model.CpModel()
    pick = {z: model.new_bool_var(z) for z in zones}
    model.add(sum(round(loads[z] * SCALE) * pick[z] for z in zones) >= round(excess * SCALE))
    # impact first, then fewest zones, then the least load removed beyond the excess (so a tie never cuts more power than it must)
    model.minimize(sum((round(impact_of.get(z, 0.0) * SCALE) * 10_000 + 100 + round(loads[z])) * pick[z] for z in zones))
    solver = cp_model.CpSolver()
    solver.parameters.num_workers, solver.parameters.random_seed, solver.parameters.max_time_in_seconds = 1, 1, time_limit_ms / 1000
    status = solver.solve(model)
    elapsed = (time.perf_counter() - started) * 1000
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return Shedding([], 0.0, 0.0, excess, Certificate(engine="shed", status="infeasible", inputs_hash=inputs_hash(problem), elapsed_ms=round(elapsed, 3)))
    chosen = [z for z in zones if solver.value(pick[z])]
    return Shedding(chosen, round(sum(loads[z] for z in chosen), 3), round(sum(impact_of.get(z, 0.0) for z in chosen), 3), round(excess, 3), Certificate(
        engine="shed", status="optimal" if status == cp_model.OPTIMAL else "feasible", objective=round(sum(impact_of.get(z, 0.0) for z in chosen), 3),
        bound=solver.best_objective_bound / (SCALE * 10_000), inputs_hash=inputs_hash(problem), elapsed_ms=round(elapsed, 3)))
