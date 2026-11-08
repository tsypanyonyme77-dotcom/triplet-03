"""Old (distance Social Force) vs new (TTC power law) pedestrian avoidance.

Runs the same scenarios through both step_pedestrian functions, updating
pedestrians in order like sim._tick_pedestrians, at dt=0.1 s.
old_social_force.py is the original module, kept only for this comparison.
Usage (from simulation/): uv run python -m tools.avoidance_comparison.compare
"""
import math
import random

from twin.engine import social_force as new
from tools.avoidance_comparison import old_social_force as old

DT = 0.1
T_MAX = 60.0
ARRIVE_M = 0.5


def run(model, starts_goals, seed=0):
    random.seed(seed)
    peds = []
    for (sx, sy), (gx, gy) in starts_goals:
        s = model.SocialForceState(x=sx, y=sy)
        peds.append({"s": s, "goal": (gx, gy), "done_at": None, "path": 0.0,
                     "turn": 0.0, "heading": None, "straight": math.hypot(gx - sx, gy - sy)})
    min_gap = math.inf
    t = 0.0
    while t < T_MAX and any(p["done_at"] is None for p in peds):
        active = [p for p in peds if p["done_at"] is None]
        for p in active:
            s = p["s"]
            nearby = [q["s"] for q in active if q is not p
                      and abs(q["s"].x - s.x) < 6 and abs(q["s"].y - s.y) < 6]
            px, py = s.x, s.y
            model.step_pedestrian(s, *p["goal"], nearby, None, 0.0, DT)
            p["path"] += math.hypot(s.x - px, s.y - py)
            sp = math.hypot(s.vx, s.vy)
            if sp > 0.2:
                h = math.atan2(s.vy, s.vx)
                if p["heading"] is not None:
                    dh = (h - p["heading"] + math.pi) % (2 * math.pi) - math.pi
                    p["turn"] += abs(dh)
                p["heading"] = h
            if math.hypot(s.x - p["goal"][0], s.y - p["goal"][1]) < ARRIVE_M:
                p["done_at"] = t
        for i, a in enumerate(active):
            for b in active[i + 1:]:
                min_gap = min(min_gap, math.hypot(a["s"].x - b["s"].x, a["s"].y - b["s"].y))
        t += DT
    stuck = sum(p["done_at"] is None for p in peds)
    done = [p for p in peds if p["done_at"] is not None]
    return {
        "min_gap_m": min_gap,
        "stuck": stuck,
        "mean_time_s": sum(p["done_at"] for p in done) / len(done) if done else float("nan"),
        "detour_pct": 100 * (sum(p["path"] / p["straight"] for p in peds) / len(peds) - 1),
        "turn_deg_per_ped": math.degrees(sum(p["turn"] for p in peds) / len(peds)),
    }


def scenarios():
    yield "head-on, exact", [((0, 0), (20, 0)), ((20, 0), (0, 0))]
    yield "head-on, 0.2 m offset", [((0, 0), (20, 0)), ((20, 0.2), (0, 0.2))]
    yield "crossing 90 deg", [((0, 10), (20, 10)), ((10, 0), (10, 20))]
    yield "side by side, same way", [((0, 0), (20, 0)), ((0, 0.8), (20, 0.8))]
    yield "two groups of 5 head-on", (
        [((0, 0.7 * i), (20, 0.7 * i)) for i in range(5)]
        + [((20, 0.7 * i + 0.35), (0, 0.7 * i + 0.35)) for i in range(5)]
    )
    rnd = random.Random(42)
    crowd = []
    for _ in range(30):  # 30 people crossing a 20 m plaza in random directions
        ang = rnd.uniform(0, 2 * math.pi)
        cx, cy = 10 + rnd.uniform(-2, 2), 10 + rnd.uniform(-2, 2)
        crowd.append(((cx - 9 * math.cos(ang), cy - 9 * math.sin(ang)),
                      (cx + 9 * math.cos(ang), cy + 9 * math.sin(ang))))
    yield "plaza, 30 random", crowd


def main():
    cols = ["min_gap_m", "stuck", "mean_time_s", "detour_pct", "turn_deg_per_ped"]
    print(f"{'scenario':28} {'model':4} " + " ".join(f"{c:>16}" for c in cols))
    for name, sg in scenarios():
        for label, model in (("old", old), ("new", new)):
            r = run(model, sg)
            print(f"{name:28} {label:4} " + " ".join(f"{r[c]:16.2f}" for c in cols))
    print("\nbodies touch below min_gap 0.60 m (2 x 0.3 m radius)")


if __name__ == "__main__":
    main()
