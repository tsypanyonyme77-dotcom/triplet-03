"""The danger zone of a burning building, as route costs.

Drivers and pedestrians keep away from a burning building: every street (and sidewalk piece or
crosswalk) that passes within HAZARD_RADIUS_M of it costs a lot more to route through. They
take another way when there is one; when there is none they go through rather than stay put,
so a fire never freezes the city. Emergency units ignore the penalties (they route on the plain
turn graph).
"""
from __future__ import annotations

import math

import networkx as nx

HAZARD_RADIUS_M = 25.0      # streets and sidewalks this close to a burning building are avoided
CAR_PENALTY_S = 600.0       # extra travel time charged for driving into an avoided street
WALK_PENALTY_M = 1000.0     # extra length charged for walking along an avoided piece of sidewalk

Point = tuple[float, float]


def segment_distance(p: Point, a: Point, b: Point) -> float:
    """Distance from point `p` to the segment a-b."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length2 = dx * dx + dy * dy
    t = 0.0 if length2 == 0 else max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / length2))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def hazard_road_edges(graph: nx.MultiDiGraph, fires: list[Point], radius_m: float = HAZARD_RADIUS_M) -> set[tuple[int, int]]:
    """The directed road edges whose centreline passes within `radius_m` of a fire."""
    out = set()
    for u, v in graph.edges():
        a, b = (graph.nodes[u]["x"], graph.nodes[u]["y"]), (graph.nodes[v]["x"], graph.nodes[v]["y"])
        if any(segment_distance(f, a, b) <= radius_m for f in fires):
            out.add((u, v))
    return out


def hazard_walk_edges(walk: nx.Graph, fires: list[Point], radius_m: float = HAZARD_RADIUS_M) -> set[frozenset]:
    """The walk-network edges (sidewalk pieces and crosswalks) within `radius_m` of a fire."""
    out = set()
    for a, b in walk.edges():
        pa, pb = (walk.nodes[a]["x"], walk.nodes[a]["y"]), (walk.nodes[b]["x"], walk.nodes[b]["y"])
        if any(segment_distance(f, pa, pb) <= radius_m for f in fires):
            out.add(frozenset((a, b)))
    return out


def with_car_penalties(turns: nx.DiGraph, hazard: set[tuple[int, int]], penalty_s: float = CAR_PENALTY_S) -> nx.DiGraph:
    """A copy of the turn graph in which entering an avoided street costs `penalty_s` more."""
    out = turns.copy()
    for edge in hazard:
        if edge in out:
            for pred in list(out.predecessors(edge)):
                out[pred][edge]["weight"] += penalty_s
    return out


def walk_weight(hazard: set[frozenset], penalty_m: float = WALK_PENALTY_M):
    """A networkx weight function for walking routes: length, plus a penalty on avoided pieces."""
    def weight(a: int, b: int, data: dict) -> float:
        return data["length"] + (penalty_m if frozenset((a, b)) in hazard else 0.0)
    return weight
