"""Synthesized roadside parking spots.

Real OSM parking data (lots, roadside tags) is essentially absent in this
area, so spots are generated procedurally along road edges: one spot every
SPOT_SPACING_M meters, offset laterally past the rightmost driving lane,
skipping the stretch near each end (intersection clearance / stop line).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import networkx as nx

from twin.engine.street_profile import parking_offset

SPOT_SPACING_M = 12.0      # distance between spot centres along the kerb: a 5.5 m bay plus room
                           # to drive in forwards on a steered curve past the car parked behind
SPOT_LENGTH_M = 5.5           # length of one parking space (car + gap)
INTERSECTION_CLEARANCE_M = 14.0  # no spots within this distance of either end of an edge: keeps the
                                   # intersection, its crosswalks (~8.5-11.5 m) and stop line (~12.5 m) clear
SEARCH_RADIUS_M = 400.0          # how far from the destination node to look for a free spot

# only place parking on lower-speed local/residential-ish roads, not primary arterials
ELIGIBLE_HIGHWAY = {"residential", "living_street", "tertiary", "unclassified"}


@dataclass
class ParkingSpot:
    id: str
    edge: tuple[int, int]     # (u, v) the spot sits alongside
    dist_on_edge: float          # position along the edge, meters from u
    occupied_by: str | None = None  # car id, or None if free


def build_parking_spots(graph: nx.MultiDiGraph) -> dict[str, ParkingSpot]:
    spots: dict[str, ParkingSpot] = {}
    for u, v, data in graph.edges(data=True):
        highway = data.get("highway")
        if isinstance(highway, list):
            highway = highway[0] if highway else None
        if highway not in ELIGIBLE_HIGHWAY:
            continue

        length = data.get("length", 0.0)
        usable_start = INTERSECTION_CLEARANCE_M
        usable_end = length - INTERSECTION_CLEARANCE_M
        if usable_end - usable_start < SPOT_LENGTH_M:
            continue

        pos = usable_start
        idx = 0
        while pos + SPOT_LENGTH_M <= usable_end:
            spot_id = f"{u}_{v}_{idx}"
            spots[spot_id] = ParkingSpot(id=spot_id, edge=(u, v), dist_on_edge=pos + SPOT_LENGTH_M / 2)
            pos += SPOT_SPACING_M
            idx += 1

    return spots


def spot_world_xy(graph: nx.MultiDiGraph, spot: ParkingSpot, lane_width: float) -> tuple[float, float, float]:
    """Returns (x, y, heading) for a spot: position at the curb, offset past the rightmost lane."""
    u, v = spot.edge
    nu, nv = graph.nodes[u], graph.nodes[v]
    dx, dy = nv["x"] - nu["x"], nv["y"] - nu["y"]
    seg_len = math.hypot(dx, dy) or 1.0
    ux, uy = dx / seg_len, dy / seg_len

    edge_data = graph.get_edge_data(u, v)[0]
    length = edge_data.get("length", seg_len)
    t = min(1.0, spot.dist_on_edge / length) if length else 0.0
    base_x = nu["x"] + dx * t
    base_y = nu["y"] + dy * t

    perp_x, perp_y = uy, -ux  # right-hand side of travel direction (lane 0 / curb side)
    offset = parking_offset(graph, u, v)  # centre of the parking lane, see street_profile.py

    x = base_x + perp_x * offset
    y = base_y + perp_y * offset
    heading = math.atan2(uy, ux)
    return x, y, heading


def spot_front_pose(graph: nx.MultiDiGraph, spot: ParkingSpot, car_length: float) -> tuple[float, float, float]:
    """Front bumper (x, y, heading) of a car parked in `spot` (the sim tracks front bumpers)."""
    x, y, heading = spot_world_xy(graph, spot, 0.0)
    return x + math.cos(heading) * car_length / 2, y + math.sin(heading) * car_length / 2, heading


def free_spots_near(
    graph: nx.MultiDiGraph, spots: dict[str, ParkingSpot], x: float, y: float, count: int, exclude: str | None = None,
    avoid_edges: frozenset | set = frozenset(),
) -> list[tuple[ParkingSpot, float]]:
    """Up to `count` free spots nearest to (x, y), with their distance, nearest first. Spots on
    `avoid_edges` (streets next to a fire) are left out before the nearest are taken."""
    found = []
    for spot in spots.values():
        if spot.occupied_by is not None or spot.id == exclude or spot.edge in avoid_edges:
            continue
        sx, sy, _ = spot_world_xy(graph, spot, 0.0)
        found.append((math.hypot(sx - x, sy - y), spot.id, spot))
    found.sort(key=lambda f: (f[0], f[1]))
    return [(spot, d) for d, _, spot in found[:count]]


def nearest_free_spot(
    graph: nx.MultiDiGraph, spots: dict[str, ParkingSpot], x: float, y: float, exclude: str | None = None
) -> ParkingSpot | None:
    """Free spot whose centre is nearest to (x, y)."""
    best, best_d = None, math.inf
    for spot in spots.values():
        if spot.occupied_by is not None or spot.id == exclude:
            continue
        sx, sy, _ = spot_world_xy(graph, spot, 0.0)
        d = math.hypot(sx - x, sy - y)
        if d < best_d:
            best, best_d = spot, d
    return best


def find_free_spot(
    graph: nx.MultiDiGraph,
    spots: dict[str, ParkingSpot],
    dest_node: int,
    radius_m: float = SEARCH_RADIUS_M,
) -> ParkingSpot | None:
    """Nearest free spot to dest_node, by straight-line distance, within radius."""
    dn = graph.nodes[dest_node]
    best: ParkingSpot | None = None
    best_dist = radius_m
    for spot in spots.values():
        if spot.occupied_by is not None:
            continue
        u, v = spot.edge
        nu = graph.nodes[u]
        d = math.hypot(nu["x"] - dn["x"], nu["y"] - dn["y"])
        if d < best_dist:
            best_dist = d
            best = spot
    return best
