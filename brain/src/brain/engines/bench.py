"""`brain optimise-bench`: how much is solving the dispatch together worth, on cities nobody tuned it for?

Random cities (grid and ring, 9 to 25 zones), random stations and bursts of incidents of different severity. For each instance the
solver is compared with nearest-first (the old rule, in arrival order): the regret is the extra severity-weighted hops nearest-first
pays. On small instances the solver is also checked against brute force. Seeds under 1000 are for design, from 1000 for scoring only.
"""

from __future__ import annotations

import itertools
import random
import statistics
from typing import Any

import networkx as nx

from brain.engines.dispatch import Demand, Supply, solve_dispatch

SEVERITIES = (1.0, 2.0, 3.0, 5.0)
UNMET = 1000


def instance(seed: int, shape: str, incidents: int, units: int) -> tuple[list[Demand], list[Supply], Any]:
    rng = random.Random(seed)
    if shape == "ring":
        graph = nx.cycle_graph(rng.randint(9, 25))
    else:
        side = rng.randint(3, 5)
        graph = nx.convert_node_labels_to_integers(nx.grid_2d_graph(side, side))
    zones = sorted(graph.nodes)
    stations = [Supply(f"s{i}", str(z), 1) for i, z in enumerate(rng.sample(zones, min(units, len(zones))))]
    demands = [Demand(f"i{n}", str(rng.choice(zones)), rng.choice(SEVERITIES)) for n in range(incidents)]
    lengths = dict(nx.all_pairs_shortest_path_length(graph))
    return demands, stations, lambda a, b: lengths[int(a)].get(int(b))


def brute_force(demands: list[Demand], supplies: list[Supply], hops: Any) -> float:
    """The cheapest assignment by trying them all (only for small instances)."""
    best = float("inf")
    options = [s.station_id for s in supplies] + [None]
    by_id = {s.station_id: s for s in supplies}
    for choice in itertools.product(options, repeat=len(demands)):
        used = [c for c in choice if c is not None]
        if any(used.count(c) > by_id[c].spare for c in set(used)):
            continue
        cost = sum(UNMET if c is None else d.severity * hops(by_id[c].zone_id, d.zone_id) for c, d in zip(choice, demands))
        best = min(best, cost)
    return best


def run(seeds: list[int], shapes: tuple[str, ...] = ("grid", "ring"), incidents: int = 4, units: int = 4) -> dict[str, Any]:
    rows = []
    for seed in seeds:
        for shape in shapes:
            demands, supplies, hops = instance(seed, shape, incidents, units)
            solution = solve_dispatch(demands, supplies, hops, unmet_penalty=UNMET)
            row = {"seed": seed, "shape": shape, "optimal": solution.certificate.objective, "nearest": solution.nearest_cost, "regret": solution.regret_vs_nearest,
                   "ms": solution.certificate.elapsed_ms}
            if incidents <= 6:
                row["brute_force"] = brute_force(demands, supplies, hops)
            rows.append(row)
    regrets = [r["regret"] for r in rows]
    times = sorted(r["ms"] for r in rows)
    return {
        "instances": len(rows), "incidents": incidents, "units": units, "seeds": [min(seeds), max(seeds)],
        "differ_share": round(sum(1 for r in regrets if r > 0) / len(rows), 3),
        "mean_regret": round(statistics.fmean(regrets), 3), "worst_regret": max(regrets),
        "mean_nearest": round(statistics.fmean(r["nearest"] for r in rows), 3), "mean_optimal": round(statistics.fmean(r["optimal"] for r in rows), 3),
        "solve_ms_p50": round(times[len(times) // 2], 3), "solve_ms_p99": round(times[min(len(times) - 1, int(len(times) * 0.99))], 3),
        "matches_brute_force": all(abs(r["optimal"] - r["brute_force"]) < 1e-6 for r in rows) if incidents <= 6 else None,
        "rows": rows,
    }


def table(result: dict[str, Any]) -> str:
    verdict = {True: "yes", False: "NO", None: "not checked (more than 6 incidents)"}[result["matches_brute_force"]]
    return "\n".join([
        f"{result['instances']} instances, {result['incidents']} incidents, {result['units']} stations, seeds {result['seeds'][0]} to {result['seeds'][1]}",
        f"nearest-first and the optimum differ on {result['differ_share']:.0%} of instances",
        f"cost (severity-weighted hops): nearest-first {result['mean_nearest']}, optimal {result['mean_optimal']}, mean regret {result['mean_regret']}, worst {result['worst_regret']}",
        f"solve time: p50 {result['solve_ms_p50']} ms, p99 {result['solve_ms_p99']} ms",
        f"matches brute force: {verdict}",
    ])
