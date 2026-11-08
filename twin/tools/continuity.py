"""Continuity check on what a scenario records: no teleports, no pop-in, no sliding.

Works on the recorded frames (twin.world.record.frame), i.e. exactly what the
viewer and the other layers see. For every vehicle and pedestrian, between two
consecutive frames (dt = 0.1 s):

  teleport  moved farther than its kind's top speed allows in one tick
  slide     moved farther than its own recorded speed allows (moving while
            reporting speed 0, e.g. a parking slide)
  crab      a vehicle's rear axle moved sideways to its heading (more than
            CRAB_DEG off it, forwards or in reverse). The rear axle, not the
            recorded front bumper: in a turn the front legitimately swings out
  yaw       heading turned faster than its kind can: for vehicles the limit is
            the bicycle model's v * tan(max steer) / wheelbase, capped by max
            lateral acceleration (v * yaw rate <= a_lat); a car standing still
            cannot turn
  accel     recorded speed changed faster than the kind's max acceleration or
            braking (e.g. stopping dead in a crash)
  pop       appeared after the first frame or vanished before the last one,
            other than a vehicle within ENTRY_RADIUS_M of a dead-end road node
            (where the road leaves the map; the two-block map has none)

Max jerk is reported, not checked. Limits are deliberately generous; a real
violation is a step change, not a borderline value.
Usage (from simulation/): uv run python -m tools.continuity [scenario ...]
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from twin.world import scenarios
from twin.world.scenarios import CityParams
from twin.world.record import frame

DT = 0.1
POSITION_SLACK_M = 0.05     # rounding and integration noise
HEADING_SLACK_RAD = math.radians(2.0)
CRAB_DEG = 15.0
ENTRY_RADIUS_M = 10.0       # vehicles may enter / leave the recording this close to a dead-end node


@dataclass(frozen=True)
class Limits:
    max_speed: float        # m/s
    max_accel: float        # m/s^2, speeding up
    max_brake: float        # m/s^2, slowing down (emergency braking, ABS)
    wheelbase: float = 0.0  # m; 0 = not a vehicle (no steering model, no crab check)
    max_steer_rad: float = 0.0
    max_lat_accel: float = 0.0
    max_yaw_rate: float = 0.0  # rad/s, pedestrians only
    front_to_rear_axle: float = 0.0  # m, recorded front bumper to rear axle (vehicles)


CAR = Limits(max_speed=17.0, max_accel=4.0, max_brake=10.0, wheelbase=2.7,
             max_steer_rad=math.radians(35), max_lat_accel=8.0, front_to_rear_axle=3.7)
AMBULANCE = Limits(max_speed=22.0, max_accel=4.0, max_brake=10.0, wheelbase=2.7,
                   max_steer_rad=math.radians(35), max_lat_accel=7.0, front_to_rear_axle=3.7)
# ambulance crew (crew_*) get out of and back into their ambulance, a hurt driver (casualty_*)
# is taken out of a wrecked car: they appear and vanish at a vehicle. A casualty loaded into an
# ambulance (status "loaded") rides inside it, and vanishes when handed over at the hospital.
GETS_OUT_OF_A_VEHICLE = ("crew_", "casualty_")
EMERGENCY_KINDS = ("ambulance", "police", "fire")  # recorded in the status field of emergency vehicles
PEDESTRIAN = Limits(max_speed=4.5, max_accel=12.0, max_brake=12.0, max_yaw_rate=3 * math.pi)


def kind_of(entity_id: str, status: str, is_pedestrian: bool) -> tuple[str, Limits]:
    if is_pedestrian:
        return "pedestrian", PEDESTRIAN
    if status in EMERGENCY_KINDS or entity_id.startswith(("amb", "police", "fire")):
        return "emergency", AMBULANCE
    return "car", CAR


def _vehicle_yaw_limit(lim: Limits, speed: float) -> float:
    if speed < 1e-3:
        return 0.0
    geometric = speed * math.tan(lim.max_steer_rad) / lim.wheelbase
    grip = lim.max_lat_accel / speed
    return min(geometric, grip)


def _angle(a: float, b: float) -> float:
    return abs(math.atan2(math.sin(b - a), math.cos(b - a)))


def entry_points(sim) -> list[tuple[float, float]]:
    """Road nodes with a single neighbour: where roads leave the map."""
    g = sim.graph
    return [
        (g.nodes[n]["x"], g.nodes[n]["y"])
        for n in g.nodes
        if len((set(g.predecessors(n)) | set(g.successors(n))) - {n}) == 1
    ]


def record_frames(name: str, seconds: float, seed: int | None = None) -> tuple[list[dict], list[tuple[float, float]]]:
    sc = scenarios.build(name, seed, CityParams().clean())
    frames, t = [], 0.0
    for _ in range(round(seconds / DT)):
        sc.step()
        t += DT
        frames.append(frame(sc.sim, t))
    return frames, entry_points(sc.sim)


def check(frames: list[dict], entries: list[tuple[float, float]], max_examples: int = 5) -> dict:
    at_entry = lambda x, y: any(math.hypot(x - ex, y - ey) <= ENTRY_RADIUS_M for ex, ey in entries)  # noqa: E731
    counts = {k: 0 for k in ("teleport", "slide", "crab", "yaw", "accel", "pop")}
    examples: dict[str, list] = {k: [] for k in counts}
    worst = {"max_accel": 0.0, "max_brake": 0.0, "max_jerk": 0.0, "max_step_m": 0.0}
    driving = {"max_accel": 0.0, "max_brake": 0.0, "max_jerk": 0.0, "max_lat_accel": 0.0}  # vehicles on the road, same status both ticks

    breakdown: dict[str, int] = {}   # "category: entity kind, status before -> after" -> count

    def flag(kind: str, *info) -> None:
        counts[kind] += 1
        if len(examples[kind]) < max_examples:
            examples[kind].append(info)
        key = f"{kind}: {where}"
        breakdown[key] = breakdown.get(key, 0) + 1

    prev: dict[str, tuple] = {}      # id -> (x, y, heading, speed, status, accel, is_pedestrian)
    for i, f in enumerate(frames):
        seen = set()
        for group, is_ped in (("cars", False), ("pedestrians", True)):
            for entity in f[group]:
                eid, x, y, heading, speed, status = entity[:6]
                seen.add(eid)
                kind, lim = kind_of(eid, status, is_ped)
                where = f"{kind} {prev[eid][4] if eid in prev else '-'} -> {status}"
                if status == "loaded" or (eid in prev and prev[eid][4] == "loaded"):
                    prev[eid] = (x, y, heading, speed, status, 0.0, is_ped)
                    continue  # a casualty inside an ambulance moves with it
                if eid not in prev:
                    if i > 0 and (is_ped or not at_entry(x, y)) and not eid.startswith(GETS_OUT_OF_A_VEHICLE):
                        flag("pop", f["t"], eid, "appears", status, round(x, 1), round(y, 1))
                    prev[eid] = (x, y, heading, speed, status, 0.0, is_ped)
                    continue
                px, py, ph, ps, pstatus, paccel, _ = prev[eid]
                if not is_ped:  # track the rear axle: it moves along the heading at the recorded speed
                    d = lim.front_to_rear_axle
                    x, y = x - math.cos(heading) * d, y - math.sin(heading) * d
                    px, py = px - math.cos(ph) * d, py - math.sin(ph) * d
                step = math.hypot(x - px, y - py)
                worst["max_step_m"] = max(worst["max_step_m"], step)
                v = max(speed, ps)
                if step > lim.max_speed * DT + POSITION_SLACK_M:
                    flag("teleport", f["t"], eid, kind, pstatus, status, round(step, 2))
                elif step > v * DT + 0.5 * lim.max_accel * DT * DT + POSITION_SLACK_M:
                    flag("slide", f["t"], eid, kind, pstatus, status, round(step, 2), "speed", round(v, 2))
                turn = _angle(ph, heading)
                if is_ped:
                    yaw_limit = lim.max_yaw_rate
                else:
                    yaw_limit = _vehicle_yaw_limit(lim, v)
                    if step > 0.05:
                        off = math.degrees(_angle(math.atan2(y - py, x - px), heading))
                        if CRAB_DEG < off < 180 - CRAB_DEG:
                            flag("crab", f["t"], eid, kind, status, round(off), round(step, 2))
                if turn > yaw_limit * DT + HEADING_SLACK_RAD:
                    flag("yaw", f["t"], eid, kind, pstatus, status, round(math.degrees(turn), 1), "speed", round(v, 2))
                accel = (speed - ps) / DT
                if accel > lim.max_accel + 0.5 or -accel > lim.max_brake + 0.5:
                    flag("accel", f["t"], eid, kind, pstatus, status, round(accel, 1))
                if accel > 0:
                    worst["max_accel"] = max(worst["max_accel"], accel)
                else:
                    worst["max_brake"] = max(worst["max_brake"], -accel)
                if not is_ped:
                    worst["max_jerk"] = max(worst["max_jerk"], abs(accel - paccel) / DT)
                    if status == pstatus and (status == "driving" or status in EMERGENCY_KINDS):
                        driving["max_accel"] = max(driving["max_accel"], accel)
                        driving["max_brake"] = max(driving["max_brake"], -accel)
                        driving["max_jerk"] = max(driving["max_jerk"], abs(accel - paccel) / DT)
                        driving["max_lat_accel"] = max(driving["max_lat_accel"], v * turn / DT)
                prev[eid] = (entity[1], entity[2], heading, speed, status, accel, is_ped)
        for eid in list(prev):
            if eid not in seen:
                x, y, _, _, status, _, is_ped = prev.pop(eid)
                where = f"{'pedestrian' if is_ped else 'vehicle'} {status} -> gone"
                if (is_ped or not at_entry(x, y)) and status != "loaded" and not eid.startswith(GETS_OUT_OF_A_VEHICLE):
                    flag("pop", f["t"], eid, "vanishes", status, round(x, 1), round(y, 1))
    return {
        "violations": counts,
        "worst": {k: round(v, 2) for k, v in worst.items()},
        "driving": {k: round(v, 2) for k, v in driving.items()},
        "examples": {k: v for k, v in examples.items() if v},
        "breakdown": dict(sorted(breakdown.items(), key=lambda kv: -kv[1])),
    }


SCENARIO_SECONDS = {"city": 180.0, "ped-hit": 90.0, "car-crash": 90.0}


def main() -> None:
    import sys

    names = [a for a in sys.argv[1:] if not a.startswith("-")] or list(SCENARIO_SECONDS)
    for name in names:
        frames, entries = record_frames(name, SCENARIO_SECONDS.get(name, 90.0))
        r = check(frames, entries)
        print(f"== {name}: {r['violations']}  worst {r['worst']}  driving {r['driving']}")
        for key, n in r["breakdown"].items():
            print(f"   {n:5d}  {key}")
        if "-v" in sys.argv:
            for kind, items in r["examples"].items():
                for item in items:
                    print(f"   {kind:8s} {item}")


if __name__ == "__main__":
    main()
