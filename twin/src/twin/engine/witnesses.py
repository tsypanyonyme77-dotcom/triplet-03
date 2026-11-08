"""Witnesses: who sees an incident, who reports it, and how wrong the report can be.

A pedestrian, a driver standing in traffic, or a driver in the crash sees an incident when it is within
WITNESS_RANGE_M and the straight line to it stays in the street corridors (between the
building lines of some street): buildings block the view, streets and their sidewalks
do not. Each witness decides once, at random, whether to call; a caller takes out a
phone after a reaction delay, stops, and calls for CALL_DURATION_S.

A call carries what the caller says, not the truth: the location can be off by a few
metres (sometimes by a block), the category can be wrong, and confidence varies.
False reports (a call about nothing) are made by Simulation.false_call_rate_per_min.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

import networkx as nx

from twin.engine.street_profile import SIDEWALK_WIDTH_M, kerb_offset

WITNESS_RANGE_M = 40.0
PEDESTRIAN_REPORT_PROB = 0.5     # share of pedestrian witnesses who call
DRIVER_REPORT_PROB = 0.3         # share of drivers stuck near it who call
INVOLVED_DRIVER_REPORT_PROB = 0.7  # a driver in the crash itself (not hurt) calls
STRANDED_DRIVER_REPORT_PROB = 0.95  # a driver stuck in a stalled car in rising water calls
REACTION_S = (1.0, 8.0)          # from first seeing it to dialling
CALL_DURATION_S = (15.0, 25.0)   # standing still on the phone
LOCATION_ERROR_SD_M = 3.0        # usual error of the reported location
FAR_OFF_PROB = 0.1               # ... a caller this often places it 15-30 m away
WRONG_CATEGORY_PROB = 0.1        # says e.g. "fire" for a crash
SIGHT_SAMPLE_M = 1.0

CATEGORIES = ("fire", "medical", "police", "flood", "other")


def true_category(accident: dict) -> str:
    """What a caller who gets it right reports: a burning building -> fire, a car or someone stuck in a
    flood -> flood, a road crash -> medical."""
    if accident["kind"] == "building_fire":
        return "fire"
    if accident["kind"] in ("flooded_car", "trapped_pedestrian"):
        return "flood"
    return "medical"   # the caller asks for an ambulance; the City Brain reads a "police" call as a crime


@dataclass
class Corridors:
    """Street centrelines with the distance to their building line, for line of sight."""
    segments: list[tuple[float, float, float, float, float]]  # ax, ay, bx, by, half width

    @classmethod
    def of(cls, graph: nx.MultiDiGraph) -> "Corridors":
        seen, segs = set(), []
        for u, v in graph.edges():
            key = (min(u, v), max(u, v))
            if key in seen:
                continue
            seen.add(key)
            a, b = graph.nodes[u], graph.nodes[v]
            segs.append((a["x"], a["y"], b["x"], b["y"], kerb_offset(graph, u, v) + SIDEWALK_WIDTH_M))
        return cls(segs)

    def open_at(self, x: float, y: float) -> bool:
        for ax, ay, bx, by, half in self.segments:
            dx, dy = bx - ax, by - ay
            length2 = dx * dx + dy * dy or 1.0
            t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / length2))
            if math.hypot(x - (ax + t * dx), y - (ay + t * dy)) <= half:
                return True
        return False

    def line_of_sight(self, x0: float, y0: float, x1: float, y1: float) -> bool:
        n = max(1, math.ceil(math.hypot(x1 - x0, y1 - y0) / SIGHT_SAMPLE_M))
        return all(self.open_at(x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n) for i in range(n + 1))


def report(accident: dict | None, x: float, y: float, rng: random.Random) -> dict:
    """What a caller says: location (with error), category, confidence. `accident` None:
    a false report about a spot (x, y) where nothing happened."""
    if accident is None:
        return {"x": round(x, 1), "y": round(y, 1), "category": rng.choice(("medical", "police")),
                "caller_confidence": round(rng.uniform(0.3, 0.7), 2)}
    err = rng.uniform(15.0, 30.0) if rng.random() < FAR_OFF_PROB else abs(rng.gauss(0.0, LOCATION_ERROR_SD_M))
    angle = rng.uniform(0, 2 * math.pi)
    category = true_category(accident)
    if rng.random() < WRONG_CATEGORY_PROB:
        category = rng.choice([c for c in CATEGORIES if c != category])
    return {"x": round(accident["x"] + err * math.cos(angle), 1), "y": round(accident["y"] + err * math.sin(angle), 1),
            "category": category, "caller_confidence": round(rng.uniform(0.6, 0.95), 2)}
