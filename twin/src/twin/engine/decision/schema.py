"""The facts a decision is made from, and how they become numbers for the student model.

This file is the training contract: the student was trained on exactly these features, in this
order. Change a table or a feature and the model must be retrained (a test compares the feature
names with the ones stored in the model file).

A *situation* is a plain dict:
    traits {name: 0..1}, role, kind ("car" | "pedestrian"), hour 0..23, current (category),
    agent_event_dist, witnessed, cand [one dict per candidate place]:
    cat, dist, open, is_home, is_anchor, crowd, d_fire, d_crash, d_closed.
Distances are in the model's metres (see situation.py for how map metres are scaled to them).
"""
from __future__ import annotations

import math

import numpy as np

CATEGORIES = ["home", "office", "grocery", "restaurant", "cafe", "school", "gym", "clinic", "pharmacy",
              "park", "bank", "hospital", "mall", "transit_stop", "worship", "market"]
HOURS = {  # opening window [start, end)
    "home": (0, 24), "office": (8, 18), "grocery": (8, 21), "restaurant": (11, 23), "cafe": (7, 22),
    "school": (8, 16), "gym": (6, 22), "clinic": (8, 17), "pharmacy": (8, 20), "park": (0, 24),
    "bank": (8, 16), "hospital": (0, 24), "mall": (10, 21), "transit_stop": (5, 23), "worship": (5, 22),
    "market": (7, 14),
}
CROWD = {"home": .1, "office": .5, "grocery": .5, "restaurant": .6, "cafe": .5, "school": .8, "gym": .5,
         "clinic": .4, "pharmacy": .3, "park": .3, "bank": .3, "hospital": .5, "mall": .9,
         "transit_stop": .7, "worship": .4, "market": .9}
TRAITS = ["urgency", "risk_aversion", "sociability", "routine", "thrift", "health_focus", "curiosity"]
ROLES = ["worker", "student", "retiree", "parent", "freelancer"]
ANCHOR = {"worker": "office", "student": "school", "parent": "school"}  # the place a role goes to by duty
EVENT_KINDS = ["fire", "crash", "closed_street"]
KINDS = ["car", "pedestrian"]
N_CAND = 12   # candidates per decision in training; fewer are fine at run time
FAR = 2000.0  # "no such event" distance


def is_open(category: str, hour: int) -> bool:
    start, end = HOURS[category]
    return start <= hour < end


def feature_names() -> list[str]:
    names = list(TRAITS) + ["role_" + r for r in ROLES]
    names += ["hour_sin", "hour_cos", "is_car", "agent_event_dist", "witnessed"]
    names += ["cur_" + c for c in CATEGORIES] + ["cat_" + c for c in CATEGORIES]
    names += ["dist", "open", "is_home", "is_anchor", "crowd", "d_fire", "d_crash", "d_closed", "d_event_min"]
    return names


def features(s: dict) -> np.ndarray:
    """One row per candidate place, columns as `feature_names()`."""
    angle = 2 * math.pi * s["hour"] / 24
    agent = [s["traits"][t] for t in TRAITS]
    agent += [1.0 if s["role"] == r else 0.0 for r in ROLES]
    agent += [math.sin(angle), math.cos(angle), 1.0 if s["kind"] == "car" else 0.0,
              s["agent_event_dist"], 1.0 if s["witnessed"] else 0.0]
    agent += [1.0 if s["current"] == c else 0.0 for c in CATEGORIES]
    rows = []
    for c in s["cand"]:
        row = agent + [1.0 if c["cat"] == k else 0.0 for k in CATEGORIES]
        row += [c["dist"], float(c["open"]), float(c["is_home"]), float(c["is_anchor"]), c["crowd"],
                c["d_fire"], c["d_crash"], c["d_closed"], min(c["d_fire"], c["d_crash"], c["d_closed"])]
        rows.append(row)
    return np.asarray(rows, dtype=np.float32)
