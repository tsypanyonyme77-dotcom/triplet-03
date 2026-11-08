"""Builds a decision situation (see schema.py) from the live simulation.

Assumptions, all tunable here:
- The clock: a simulated day passes in 24 minutes (`CLOCK_SPEEDUP` = 60), starting at 08:00, so
  opening hours matter within a demo.
- Map scale: the model was trained on trips with a median distance of 500 m, the two-block map
  has places a median 80 m apart. Every map distance is multiplied by a map-wide factor so the
  median place-to-place distance becomes the training median.
"""
from __future__ import annotations

import math
import random
import statistics

from twin.engine.decision.profile import AgentProfile
from twin.engine.decision.schema import CROWD, FAR, N_CAND, is_open

START_HOUR = 8
CLOCK_SPEEDUP = 60.0
TRAIN_MEDIAN_DIST = 500.0
DIST_RANGE = (60.0, 2500.0)       # what the model has seen
AT_PLACE_M = 25.0                 # closer than this (map metres) to a place = standing at it
WITNESS_M = 80.0                  # model metres: an event this close is seen by the road user
P_HOME, P_ANCHOR = 0.8, 0.7       # how often training offered the home and the duty place


def clock_hour(sim_time: float, start_hour: int = START_HOUR) -> int:
    return int(start_hour + sim_time * CLOCK_SPEEDUP / 3600.0) % 24


def map_scale(places: list[dict]) -> float:
    pairs = [math.hypot(a["x"] - b["x"], a["y"] - b["y"]) for i, a in enumerate(places) for b in places[i + 1:]]
    median = statistics.median(pairs) if pairs else 0.0
    return TRAIN_MEDIAN_DIST / median if median > 0 else 1.0


def place_here(places: list[dict], x: float, y: float) -> tuple[dict, bool]:
    """The place nearest to (x, y), and whether the road user is standing at it."""
    nearest = min(places, key=lambda p: math.hypot(p["x"] - x, p["y"] - y))
    return nearest, math.hypot(nearest["x"] - x, nearest["y"] - y) <= AT_PLACE_M


def event_points(sim) -> dict[str, list[tuple[float, float]]]:
    """Where things are going wrong, in map metres. Fire joins when a fire scenario exists."""
    crashes = [(a["x"], a["y"]) for a in sim.accidents if a.get("cleared_t") is None]
    closed = []
    for u, v in sim.closed_edges:
        a, b = sim.graph.nodes[u], sim.graph.nodes[v]
        closed.append(((a["x"] + b["x"]) / 2, (a["y"] + b["y"]) / 2))
    return {"fire": [], "crash": crashes, "closed_street": closed}


def _nearest(x: float, y: float, points: list[tuple[float, float]], scale: float) -> float:
    if not points:
        return FAR
    return min(FAR, min(math.hypot(x - px, y - py) for px, py in points) * scale)


def pick_candidates(entity, profile: AgentProfile, pool: list[dict], here: dict | None, rng: random.Random) -> list[dict]:
    """Up to N_CAND places to choose from: the person's own home and duty place (as often as in
    training), the rest at random. Other people's homes are not destinations."""
    options = [p for p in pool if p is not here and (p["category"] != "home" or p["id"] == profile.home_id)]
    chosen = [p for p in options
              if (p["id"] == profile.home_id and rng.random() < P_HOME)
              or (p["id"] == profile.anchor_id and rng.random() < P_ANCHOR)]
    rest = [p for p in options if p not in chosen]
    return chosen + rng.sample(rest, min(N_CAND - len(chosen), len(rest)))


def build_situation(sim, entity, kind: str, profile: AgentProfile, scale: float, rng: random.Random,
                    start_hour: int = START_HOUR) -> tuple[dict, list[dict]]:
    """Returns the situation and the places its candidates stand for, in the same order."""
    hour = clock_hour(sim._sim_time, start_hour)
    nearest, at_place = place_here(sim.places, entity.x, entity.y)
    places = pick_candidates(entity, profile, sim.nearby_places(entity), nearest if at_place else None, rng)
    events = event_points(sim)
    agent_event = min((_nearest(entity.x, entity.y, pts, scale) for pts in events.values()), default=FAR)
    cands = []
    for p in places:
        d = max(DIST_RANGE[0], min(DIST_RANGE[1], math.hypot(p["x"] - entity.x, p["y"] - entity.y) * scale))
        cands.append({
            "cat": p["category"], "dist": round(d), "open": is_open(p["category"], hour),
            "is_home": p["id"] == profile.home_id, "is_anchor": p["id"] == profile.anchor_id,
            "crowd": CROWD[p["category"]],
            "d_fire": _nearest(p["x"], p["y"], events["fire"], scale),
            "d_crash": _nearest(p["x"], p["y"], events["crash"], scale),
            "d_closed": _nearest(p["x"], p["y"], events["closed_street"], scale),
        })
    situation = {"traits": profile.traits, "role": profile.role, "kind": kind, "hour": hour,
                 "current": nearest["category"], "cand": cands, "agent_event_dist": agent_event,
                 "witnessed": agent_event < WITNESS_M}
    return situation, places
