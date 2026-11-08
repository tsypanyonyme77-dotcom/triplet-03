"""Routes between parking spots, without U-turns.

A car starts on a known edge (its parking spot's street, in the spot's direction)
and must end on the destination spot's edge. Routing on the road graph's nodes
would allow u -> v -> u: a U-turn inside a 5 m lane, which a 2.7 m wheelbase car
cannot steer (minimum turning radius about 3.9 m). So routes are searched on the
edge graph instead: one node per directed edge (u, v), linked to (v, w) for every
w != u. A U-turn is kept only where it is the only way on (a dead end).
"""
from __future__ import annotations

import networkx as nx

Edge = tuple[int, int]


def build_turn_graph(road: nx.MultiDiGraph) -> nx.DiGraph:
    turns = nx.DiGraph()
    for u, v, data in road.edges(data=True):
        turns.add_node((u, v))
    for u, v in list(turns.nodes):
        onward = [w for w in road.successors(v) if w != v]
        allowed = [w for w in onward if w != u] or onward  # dead end: turning round is the only way
        for w in allowed:
            turns.add_edge((u, v), (v, w), weight=road.get_edge_data(v, w)[0].get("travel_time", 1.0))
    return turns


def route_between(
    turns: nx.DiGraph, start: Edge, start_dist: float, dest: Edge, dest_dist: float, min_same_edge_m: float
) -> list[int] | None:
    """Node route from `start_dist` on edge `start` to `dest_dist` on edge `dest`.

    A destination further along the same edge (by at least `min_same_edge_m`, room to
    pull out and in) is reached directly; otherwise the car drives on and comes back
    round the block. None if there is no way, also when `start` or `dest` is not in `turns`:
    a closed street is taken out of it, and a car can be parked on one or be heading for one."""
    if start not in turns or dest not in turns:
        return None
    if start == dest and dest_dist >= start_dist + min_same_edge_m:
        return [start[0], start[1]]
    if start not in turns or dest not in turns:
        return None  # the street it is on, or the one it is going to, is closed
    best: list[Edge] | None = None
    best_cost = float("inf")
    for nxt in turns.successors(start):
        try:
            cost, path = nx.single_source_dijkstra(turns, nxt, dest, weight="weight")
        except nx.NetworkXNoPath:
            continue
        if cost < best_cost:
            best, best_cost = path, cost
    if best is None:
        return None
    return [start[0], start[1]] + [edge[1] for edge in best]


def route_length(road: nx.MultiDiGraph, route: list[int], start_dist: float, end_dist: float) -> float:
    """Metres driven along `route` from start_dist on its first edge to end_dist on its last."""
    lengths = [road.get_edge_data(u, v)[0].get("length", 1.0) for u, v in zip(route, route[1:])]
    return sum(lengths[:-1]) - start_dist + end_dist
