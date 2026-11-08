"""Synthetic points of interest: everyday destinations (homes, workplaces,
shops, amenities) scattered across the road network.

Real OSM POI data in this area is sparse and skewed toward gas stations, so
for a believable mix of trip generators (home -> work, work -> grocery, etc.)
we generate them procedurally instead. Positions sit off the road edge like
a building would, picked from a deterministic-random sample of road segments
so the mix is reproducible across restarts.
"""
from __future__ import annotations

import math
import random

import networkx as nx

from twin.engine.road_network import LANE_WIDTH_M

TOTAL_PLACES = 100
BUILDING_SETBACK_M = 4.0   # gap between the road edge and the building marker
PLACE_SEED = 20241108        # fixed seed: same map -> same synthetic places every run

# (category, display label, weight) - weight sets relative frequency, homes dominate
CATEGORIES: list[tuple[str, str, int]] = [
    ("home", "Residence", 40),
    ("office", "Office", 12),
    ("grocery", "Grocery Store", 10),
    ("restaurant", "Restaurant", 8),
    ("cafe", "Cafe", 6),
    ("school", "School", 5),
    ("gym", "Gym", 4),
    ("clinic", "Clinic", 4),
    ("pharmacy", "Pharmacy", 3),
    ("park", "Park", 3),
    ("bank", "Bank", 2),
    ("hospital", "Hospital", 1),
    ("mall", "Shopping Mall", 2),
]

ELIGIBLE_HIGHWAY = {"residential", "living_street", "tertiary", "unclassified", "secondary"}


def _weighted_category(rng: random.Random) -> tuple[str, str]:
    total = sum(w for _, _, w in CATEGORIES)
    pick = rng.uniform(0, total)
    acc = 0.0
    for category, label, weight in CATEGORIES:
        acc += weight
        if pick <= acc:
            return category, label
    return CATEGORIES[-1][0], CATEGORIES[-1][1]


def generate_places(graph: nx.MultiDiGraph, count: int = TOTAL_PLACES) -> list[dict]:
    eligible_edges = []
    for u, v, data in graph.edges(data=True):
        highway = data.get("highway")
        if isinstance(highway, list):
            highway = highway[0] if highway else None
        if highway not in ELIGIBLE_HIGHWAY:
            continue
        length = data.get("length", 0.0)
        if length < 10.0:
            continue
        eligible_edges.append((u, v, data))

    if not eligible_edges:
        return []

    rng = random.Random(PLACE_SEED)
    category_counts: dict[str, int] = {}
    places = []

    for _ in range(count):
        u, v, data = rng.choice(eligible_edges)
        nu, nv = graph.nodes[u], graph.nodes[v]
        dx, dy = nv["x"] - nu["x"], nv["y"] - nu["y"]
        seg_len = math.hypot(dx, dy) or 1.0
        ux, uy = dx / seg_len, dy / seg_len

        length = data.get("length", seg_len)
        t = rng.uniform(0.15, 0.85)  # avoid clustering right at intersections
        base_x = nu["x"] + dx * t
        base_y = nu["y"] + dy * t

        lanes = data.get("lanes", 1)
        road_half_width = lanes * LANE_WIDTH_M / 2.0
        perp_x, perp_y = uy, -ux
        side = rng.choice([-1, 1])  # either side of the street, unlike parking's fixed curb
        offset = side * (road_half_width + BUILDING_SETBACK_M)

        category, label = _weighted_category(rng)
        category_counts[category] = category_counts.get(category, 0) + 1
        name = f"{label} {category_counts[category]}"

        nearest_node = u if t < 0.5 else v

        places.append(
            {
                "id": f"place_{len(places)}",
                "name": name,
                "category": category,
                "x": base_x + perp_x * offset,
                "y": base_y + perp_y * offset,
                "nearest_node": nearest_node,
            }
        )

    return places


# What a building can be when places are the map's own buildings. A hospital is left out: the
# map's hospital is its station, drawn and named on its own.
BUILDING_CATEGORIES = [(c, label, w) for c, label, w in CATEGORIES if c != "hospital"]


def _category_shares(count: int) -> list[tuple[str, str]]:
    """`count` (category, label) pairs in proportion to the weights (largest remainder), so a
    small map keeps the mix of a big one: mostly homes, a few of everything else."""
    total = sum(w for _, _, w in BUILDING_CATEGORIES)
    exact = [(c, label, count * w / total) for c, label, w in BUILDING_CATEGORIES]
    whole = {c: int(x) for c, _, x in exact}
    leftovers = sorted(exact, key=lambda e: e[2] - int(e[2]), reverse=True)
    for c, _, _ in leftovers[: count - sum(whole.values())]:
        whole[c] += 1
    return [(c, label) for c, label, _ in BUILDING_CATEGORIES for _ in range(whole[c])]


def places_from_buildings(graph: nx.MultiDiGraph, buildings: list) -> list[dict]:
    """One place per building: the building is the destination, its name is painted on its walls.
    A place stands where its building is reached from the street (`front`). Deterministic: the
    same map gives the same places."""
    rng = random.Random(PLACE_SEED)
    shares = _category_shares(len(buildings))
    rng.shuffle(shares)
    counts: dict[str, int] = {}
    places = []
    for building, (category, label) in zip(buildings, shares):
        counts[category] = counts.get(category, 0) + 1
        fx, fy = building.front
        nearest = min(graph.nodes, key=lambda n: (graph.nodes[n]["x"] - fx) ** 2 + (graph.nodes[n]["y"] - fy) ** 2)
        places.append({
            "id": f"place_{len(places)}", "name": f"{label} {counts[category]}", "category": category,
            "x": fx, "y": fy, "nearest_node": nearest, "building_id": building.id,
        })
    return places
