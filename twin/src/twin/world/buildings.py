"""The buildings of a street grid: a ring of boxes around every block, behind the sidewalks.

Each block (the cell between neighbouring street lines) gets a row of buildings along its
south and north streets and a column along its west and east streets, 14 m deep and about
12 m wide, with a metre between neighbours. Heights are drawn per block from a fixed seed, so
a map always has the same skyline. The viewer draws these boxes; the engine lets them burn.
"""
from __future__ import annotations

import math
import random

import networkx as nx

from twin.engine.buildings import Building
from twin.engine.street_profile import SIDEWALK_WIDTH_M, kerb_offset

ROW_DEPTH_M = 14.0
BUILDING_WIDTH_M = 12.0
GAP_M = 1.0                       # between neighbours in a row
HEIGHT_RANGE_M = (8.0, 30.0)
FACE_INSET_M = 0.5                # a building's `front` is this far inside the street corridor


def _along(start: float, end: float) -> list[tuple[float, float]]:
    """(centre, width) of the buildings that fill [start, end]."""
    n = math.floor((end - start) / BUILDING_WIDTH_M)
    if n < 1:
        return []
    width = (end - start) / n
    return [(start + width * (i + 0.5), width - GAP_M) for i in range(n)]


def build_buildings(graph: nx.MultiDiGraph) -> list[Building]:
    """Every block of the (rectangular) street grid of `graph`, ringed with buildings."""
    node_at = {(round(d["x"], 3), round(d["y"], 3)): n for n, d in graph.nodes(data=True)}
    xs = sorted({x for x, _ in node_at})
    ys = sorted({y for _, y in node_at})
    u, v = next(iter(graph.edges()))[:2]
    inset = kerb_offset(graph, u, v) + SIDEWALK_WIDTH_M   # the building line, from a street's centreline
    face = inset - FACE_INSET_M

    def street(a: tuple[float, float], b: tuple[float, float]) -> tuple[int, int]:
        na, nb = node_at.get(a), node_at.get(b)
        return (min(na, nb), max(na, nb)) if na is not None and nb is not None else (0, 0)

    buildings: list[Building] = []
    block = 0
    for i in range(len(xs) - 1):
        for j in range(len(ys) - 1):
            block += 1
            x0, x1, y0, y1 = xs[i], xs[i + 1], ys[j], ys[j + 1]
            rng = random.Random(block)
            height = lambda: rng.uniform(*HEIGHT_RANGE_M)  # noqa: E731
            south, north = street((x0, y0), (x1, y0)), street((x0, y1), (x1, y1))
            west, east = street((x0, y0), (x0, y1)), street((x1, y0), (x1, y1))
            made: list[tuple] = []
            for c, w in _along(x0 + inset, x1 - inset):
                made.append((c, y0 + inset + ROW_DEPTH_M / 2, w, ROW_DEPTH_M, south, (c, y0 + face)))
                made.append((c, y1 - inset - ROW_DEPTH_M / 2, w, ROW_DEPTH_M, north, (c, y1 - face)))
            for c, w in _along(y0 + inset + ROW_DEPTH_M, y1 - inset - ROW_DEPTH_M):
                made.append((x0 + inset + ROW_DEPTH_M / 2, c, ROW_DEPTH_M, w, west, (x0 + face, c)))
                made.append((x1 - inset - ROW_DEPTH_M / 2, c, ROW_DEPTH_M, w, east, (x1 - face, c)))
            for k, (x, y, width, depth, facing, front) in enumerate(made, start=1):
                buildings.append(Building(id=f"bld-{block:02d}-{k:02d}", x=x, y=y, width=width, depth=depth,
                                          height=height(), street=facing, front=front))
    return buildings
