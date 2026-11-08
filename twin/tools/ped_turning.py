"""Do pedestrians turn on the spot? The viewer turns the model to the recorded heading,
so a heading that swings while the body stands still is a figure spinning on screen.

For every pedestrian on foot, over each WINDOW_S sliding window:
  spin windows   windows where the heading turns more than SPIN_DEG in total
                 while the body moves less than STILL_M (turning on the spot)
  spinners       pedestrians with at least one spin window
A person turning around once (180 degrees) to walk back stays well under SPIN_DEG.
Usage (from simulation/): uv run python -m tools.ped_turning [scenario ...]
"""
from __future__ import annotations

import math
import sys
from collections import deque

from twin.world import scenarios
from twin.world.scenarios import CityParams

WINDOW_S = 3.0
SPIN_DEG = 360.0  # a full turn; the body may turn up to 540 degrees in a window (app/ped_facing.py)
STILL_M = 1.0
ON_FOOT = ("walking", "waiting", "arrived")


def _turn(a: float, b: float) -> float:
    return abs(math.atan2(math.sin(b - a), math.cos(b - a)))


def measure(name: str = "city", seconds: float = 180.0, seed: int | None = None) -> dict:
    sc = scenarios.build(name, seed, CityParams().clean())
    sim = sc.sim
    window = round(WINDOW_S / 0.1)
    tracks: dict[str, deque] = {}
    out = {"spin_windows": 0, "spin_windows_by_status": {}, "spinners": set()}
    for _ in range(round(seconds / 0.1)):
        sc.step()
        for ped in sim.pedestrians.values():
            if ped.status not in ON_FOOT:
                tracks.pop(ped.id, None)
                continue
            track = tracks.setdefault(ped.id, deque(maxlen=window + 1))
            track.append((ped.x, ped.y, ped.heading))
            if len(track) <= window:
                continue
            turned = sum(_turn(a[2], b[2]) for a, b in zip(track, list(track)[1:]))
            moved = math.hypot(track[-1][0] - track[0][0], track[-1][1] - track[0][1])
            if math.degrees(turned) > SPIN_DEG and moved < STILL_M:
                out["spin_windows"] += 1
                by = out["spin_windows_by_status"]
                by[ped.status] = by.get(ped.status, 0) + 1
                out["spinners"].add(ped.id)
    out["spinners"] = len(out["spinners"])
    return out


if __name__ == "__main__":
    for name in sys.argv[1:] or list(scenarios.SCENARIOS):
        print(name, measure(name))
