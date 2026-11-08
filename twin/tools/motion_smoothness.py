"""How smoothly do cars move, tick to tick? The viewer only shows what the engine
records, so a snap here is a snap on screen.

For every driving car (and ambulance on a call), between consecutive ticks:
  heading snaps   ticks where the heading turns more than SNAP_DEG
  max turn        largest heading change in one tick (degrees)
  jumps           ticks where the position moves more than the car's own travel
                  (speed x dt) plus JUMP_SLACK_M, i.e. a sideways or backward snap
  max jump        largest such extra displacement (m)
Parking pull-ins are reported apart (they are a separate, known issue).
Usage (from simulation/): uv run python -m tools.motion_smoothness
"""
from __future__ import annotations

import math

from twin.world import scenarios
from twin.world.scenarios import CityParams

SNAP_DEG = 20.0      # a car at 50 km/h turning a 6 m radius corner turns ~13 degrees per 0.1 s
JUMP_SLACK_M = 0.5


def measure(name: str = "city", seconds: float = 180.0, seed: int | None = None) -> dict:
    sc = scenarios.build(name, seed, CityParams().clean())
    sim = sc.sim
    prev: dict[str, tuple[float, float, float, float, str]] = {}
    out = {"heading_snaps": 0, "max_turn_deg": 0.0, "jumps": 0, "max_jump_m": 0.0, "parking_slide_max_m": 0.0, "car_ticks": 0}
    for _ in range(round(seconds / 0.1)):
        sc.step()
        movers = [c for c in sim.cars.values() if c.status in ("driving", "parking")]
        movers += [u for u in sim.units.values() if not u.finished and u.status in ("dispatched", "returning")]
        for c in movers:
            status = getattr(c, "status", "driving")
            state = (c.x, c.y, c.heading, c.speed, status)
            if c.id in prev:
                px, py, ph, pspeed, pstatus = prev[c.id]
                step = math.hypot(c.x - px, c.y - py)
                if status == "parking" or pstatus == "parking":
                    out["parking_slide_max_m"] = max(out["parking_slide_max_m"], step)
                elif status == pstatus and status in ("driving", "dispatched", "returning"):
                    out["car_ticks"] += 1
                    turn = abs(math.degrees(math.atan2(math.sin(c.heading - ph), math.cos(c.heading - ph))))
                    out["max_turn_deg"] = max(out["max_turn_deg"], turn)
                    out["heading_snaps"] += turn > SNAP_DEG
                    extra = step - max(c.speed, pspeed) * 0.1
                    if extra > JUMP_SLACK_M:
                        out["jumps"] += 1
                        out["max_jump_m"] = max(out["max_jump_m"], extra)
            prev[c.id] = state
        for gone in set(prev) - {c.id for c in movers}:
            prev.pop(gone)
    return {k: round(v, 2) if isinstance(v, float) else v for k, v in out.items()}


if __name__ == "__main__":
    for name in ("city", "ped-hit", "car-crash"):
        print(name, measure(name))
