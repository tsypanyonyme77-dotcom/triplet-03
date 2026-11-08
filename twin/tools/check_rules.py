"""Checks the movement rules on the real Simulation, from geometry only, so it
runs against the baseline and the current engine alike.

Spec (the cross-section the new code implements; see app/street_profile.py):
  asphalt is |offset from street centreline| < KERB_M; the sidewalk runs from
  KERB_M to BUILDING_LINE_M; crosswalks are bands CROSSWALK_W wide centred
  CROSSWALK_ALONG_M from each intersection along each arm.
Rules:
  R1  a pedestrian on foot (walking, waiting, arrived) is never on asphalt
      outside a crosswalk band
  R1b a pedestrian's body never goes past the building line (into a block, or
      off the map): it stays within BUILDING_LINE_M of some street
  R1c the straight path between two ticks never crosses asphalt outside a
      crosswalk band (catches cutting across a street between ticks)
  R1d a pedestrian who is not distracted steps onto a signalised crosswalk only
      on the WALK signal
  R2  no two pedestrians overlap (centre distance < 2 x body radius)
  R3  a car stopped at a red light has its front before the crosswalk, and is
      never pushed backwards along its edge
  R4  a car driving into a pedestrian is flagged as an accident (forced scenario)
  R5  a car never stands still (below 0.1 m/s) with any part of its body on a
      crosswalk or inside an intersection box (crashed cars excepted, and cars
      giving way to a pedestrian on a crosswalk just ahead of them, e.g. a
      distracted one who stepped out in front of a car already in the junction;
      ambulances may stop anywhere on a call)
  R6  no two car bodies overlap (crashed pairs excepted): every overlap must be a
      real, detected crash
Usage (from simulation/): uv run python -m tools.check_rules
"""
from __future__ import annotations

import math
import sys

from twin.engine.car_collisions import body_corners, overlap_depth
from twin.world.map import NODES, STREETS
from twin.engine.traffic_lights import WALK
from twin.world.scenario import build_simulation, step

KERB_M = 8.0
SIDEWALK_M = 4.0
BUILDING_LINE_M = KERB_M + SIDEWALK_M
CROSSWALK_ALONG_M = 10.0
CROSSWALK_W = 3.0
BODY_RADIUS_M = 0.3
BODY_DIAMETER_M = 2 * BODY_RADIUS_M
PATH_SAMPLE_M = 0.1
INTERSECTIONS = {n for n in NODES if sum(n in s for s in STREETS) >= 3}
# Rules measured but not yet enforced: cars cannot see a leader across an intersection and do
# not keep the box clear yet (feat/realistic-physics step 4). Reported, excluded from PASS/FAIL.
# rules measured but not enforced yet (rule_violations leaves them out); none at the moment
OPEN_RULES: frozenset[str] = frozenset()
STEPPING_OFF_M = 2.5  # R5: a pedestrian this close past the kerb still holds the car
YIELD_AHEAD_M = 6.0   # R5: a car waits for a pedestrian on the crosswalk under this much road ahead of it


def giving_way(car, peds_on_crosswalks) -> bool:
    """A pedestrian is on the crosswalk the car is about to drive over (under the next
    YIELD_AHEAD_M in front of its bumper)."""
    ux, uy = math.cos(car.heading), math.sin(car.heading)
    ahead = {crosswalk_band(car.x + ux * s / 2, car.y + uy * s / 2) for s in range(int(YIELD_AHEAD_M * 2) + 1)}
    ahead.discard(None)
    return any(crossing_band(p) in ahead for p in peds_on_crosswalks)


def crossing_band(ped) -> tuple[int, int] | None:
    """The crosswalk a pedestrian is on, or has just stepped off (within STEPPING_OFF_M
    behind them): drivers wait until they are clear of the kerb, as the engine does."""
    band = crosswalk_band(ped.x, ped.y)
    if band is None:
        h = ped.heading
        band = crosswalk_band(ped.x - math.cos(h) * STEPPING_OFF_M, ped.y - math.sin(h) * STEPPING_OFF_M)
    return band


def rule_violations(result: dict) -> dict:
    """Enforced rules with a non-zero count."""
    return {k: n for k, n in result.items() if k.startswith("R") and n and k not in OPEN_RULES}
ON_FOOT = ("walking", "waiting", "arrived", "calling")


def _street_frame(a: int, b: int, x: float, y: float) -> tuple[float, float, float]:
    """(along from a, |lateral| from the centreline, street length) of point x, y."""
    (ax, ay), (bx, by) = NODES[a], NODES[b]
    length = math.hypot(bx - ax, by - ay)
    ux, uy = (bx - ax) / length, (by - ay) / length
    along = (x - ax) * ux + (y - ay) * uy
    lateral = abs(-(x - ax) * uy + (y - ay) * ux)
    return along, lateral, length


def crosswalk_band(x: float, y: float) -> tuple[int, int] | None:
    """(intersection node, crossed arm) of the crosswalk whose asphalt the point is on."""
    for a, b in STREETS:
        along, lateral, length = _street_frame(a, b, x, y)
        if lateral >= KERB_M:
            continue
        for node, arm, d in ((a, b, along), (b, a, length - along)):
            if node in INTERSECTIONS and abs(d - CROSSWALK_ALONG_M) <= CROSSWALK_W / 2:
                return node, arm
    return None


def on_asphalt_outside_crosswalk(x: float, y: float) -> bool:
    for a, b in STREETS:
        along, lateral, length = _street_frame(a, b, x, y)
        if lateral >= KERB_M or along < -KERB_M or along > length + KERB_M:
            continue
        # includes the intersection squares: no legal pedestrian spot lies inside one
        if crosswalk_band(x, y) is None:
            return True
    return False


def body_points(x: float, y: float, heading: float, length: float) -> list[tuple[float, float]]:
    """Corners, edge midpoints and centre of a car body behind its front bumper."""
    c = body_corners(x, y, heading, length)
    mids = [((c[i][0] + c[(i + 1) % 4][0]) / 2, (c[i][1] + c[(i + 1) % 4][1]) / 2) for i in range(4)]
    centre = ((c[0][0] + c[2][0]) / 2, (c[0][1] + c[2][1]) / 2)
    return c + mids + [centre]


def in_junction_box(x: float, y: float) -> bool:
    return any(abs(x - NODES[n][0]) < KERB_M and abs(y - NODES[n][1]) < KERB_M for n in INTERSECTIONS)


def past_building_line(x: float, y: float, radius: float = BODY_RADIUS_M) -> bool:
    """True if a body at x, y reaches past the building line of every street,
    i.e. into a block or off the map."""
    for a, b in STREETS:
        along, lateral, length = _street_frame(a, b, x, y)
        reach = BUILDING_LINE_M - radius
        if lateral <= reach and -reach <= along <= length + reach:
            return False
    return True


def path_crosses_road(x0: float, y0: float, x1: float, y1: float) -> bool:
    steps = max(1, math.ceil(math.hypot(x1 - x0, y1 - y0) / PATH_SAMPLE_M))
    return any(
        on_asphalt_outside_crosswalk(x0 + (x1 - x0) * i / steps, y0 + (y1 - y0) * i / steps)
        for i in range(1, steps)
    )


def run_movement_checks(seconds: float, scenario=None, **kw) -> dict:
    """Random traffic built from `kw`, or a scripted twin.world.scenarios.Scenario."""
    if scenario is None:
        sim = build_simulation(**kw)
        advance = lambda: step(sim)  # noqa: E731
    else:
        sim, advance = scenario.sim, scenario.step
    v = {
        "R1_ped_on_road_ticks": 0,
        "R1b_ped_past_building_line_ticks": 0,
        "R1c_ped_path_across_road": 0,
        "R1d_ped_entered_crosswalk_without_walk": 0,
        "R2_ped_overlap_ticks": 0,
        "R3_stopped_past_line": 0,
        "R3_pushed_back": 0,
        "R5_car_stopped_on_crosswalk_or_junction": 0,
        "R6_car_overlap_ticks": 0,
    }
    walking_ticks = 0
    last = {}
    prev_pos: dict[str, tuple[float, float]] = {}
    prev_band: dict[str, tuple[int, int] | None] = {}
    for _ in range(int(seconds / 0.1)):
        advance()
        peds = [p for p in sim.pedestrians.values() if p.status in ON_FOOT]
        for p in peds:
            if p.status != "arrived":
                walking_ticks += 1
            if on_asphalt_outside_crosswalk(p.x, p.y):
                v["R1_ped_on_road_ticks"] += 1
            if past_building_line(p.x, p.y):
                v["R1b_ped_past_building_line_ticks"] += 1
            if p.id in prev_pos and path_crosses_road(*prev_pos[p.id], p.x, p.y):
                v["R1c_ped_path_across_road"] += 1
            band = crosswalk_band(p.x, p.y)
            if band and prev_band.get(p.id) is None and p.id in prev_band and not p.distracted:
                node, arm = band
                light = sim.traffic_lights.get(node)
                if light is not None and light.walk_state != WALK:
                    v["R1d_ped_entered_crosswalk_without_walk"] += 1
            prev_pos[p.id] = (p.x, p.y)
            prev_band[p.id] = band
        for i, p in enumerate(peds):
            for q in peds[i + 1:]:
                if math.hypot(p.x - q.x, p.y - q.y) < BODY_DIAMETER_M - 0.02:
                    v["R2_ped_overlap_ticks"] += 1
        bodies = [
            c for c in list(sim.cars.values()) + [u for u in sim.units.values() if not u.finished]
            if getattr(c, "status", "") != "crashed"
        ]
        on_crosswalks = [p for p in peds if p.status == "walking" and crossing_band(p)]
        for c in bodies:
            if c.id in sim.units:
                continue  # R5 is about cars: an emergency vehicle stops at the scene, even in a junction
            if c.speed < 0.1 and any(
                crosswalk_band(x, y) or in_junction_box(x, y) for x, y in body_points(c.x, c.y, c.heading, c.params.length)
            ) and not giving_way(c, on_crosswalks):
                v["R5_car_stopped_on_crosswalk_or_junction"] += 1
        for i, a in enumerate(bodies):
            for b in bodies[i + 1:]:
                if abs(a.x - b.x) > 10 or abs(a.y - b.y) > 10:
                    continue
                if overlap_depth(body_corners(a.x, a.y, a.heading, a.params.length),
                                 body_corners(b.x, b.y, b.heading, b.params.length)) > 0.05:
                    v["R6_car_overlap_ticks"] += 1
        for c in sim.cars.values():
            if c.finished or c.status != "driving":
                last.pop(c.id, None)
                continue
            u, w = c.route_nodes[c.edge_index], c.route_nodes[c.edge_index + 1]
            key = (u, w, c.edge_index)
            if c.id in last and last[c.id][0] == key and c.dist_on_edge < last[c.id][1] - 1e-6:
                v["R3_pushed_back"] += 1
            last[c.id] = (key, c.dist_on_edge)
            light = sim.traffic_lights.get(w)
            if light and light.state_for_approach(u) == "red" and c.speed < 0.1:
                remaining = sim.edge_length(u, w) - c.dist_on_edge
                if remaining < CROSSWALK_ALONG_M + CROSSWALK_W / 2:
                    v["R3_stopped_past_line"] += 1
    v["walking_ticks"] = walking_ticks
    v["accidents"] = len(getattr(sim, "accidents", []))
    return v


def run_forced_collision() -> str:
    """A pedestrian frozen in the middle of a lane, a car driving straight at it
    with pedestrian yielding switched off: must produce exactly one accident."""
    sim = build_simulation(cars=0, pedestrians=1, runners=0)
    if not hasattr(sim, "accidents"):
        return "FAIL: Simulation has no accident detection (no .accidents)"
    car = sim.spawn_car(1, 3)  # along y=0, east
    car.yield_to_pedestrians = False
    ped = next(iter(sim.pedestrians.values()))
    ped.status, ped.finished, ped.loop = "walking", True, False  # frozen: not stepped by the sim
    ped.force.x, ped.force.y = 40.0, -2.5  # middle of the eastbound lane
    for _ in range(200):
        sim.tick(0.1)
        if sim.accidents:
            break
    if len(sim.accidents) != 1:
        return f"FAIL: expected 1 accident, got {len(sim.accidents)}"
    a = sim.accidents[0]
    flagged = a["car_id"] == car.id and a["pedestrian_id"] == ped.id and car.status == "crashed"
    in_state = any(x["id"] == a["id"] for x in sim.state()["accidents"])
    for _ in range(600):  # a minute on: nothing is dispatched, the accident stays open
        sim.tick(0.1)
    still_open = a["cleared_t"] is None and car.id in sim.cars and ped.id in sim.pedestrians
    cleared = still_open and sim.clear_accident(a["id"]) and car.id not in sim.cars and ped.id not in sim.pedestrians
    ok = flagged and in_state and cleared
    return ("PASS: " if ok else "FAIL: ") + f"flagged={flagged} in_state={in_state} cleared_by_call={cleared} {a}"


CONFIGS = (
    ("spike 5 cars / 5 peds", {"cars": 5, "pedestrians": 5, "runners": 2, "distracted": 1}),
    ("dense 15 cars / 25 peds", {"cars": 15, "pedestrians": 25, "runners": 5}),
)
SEEDS = (7, 11, 23)


def main() -> None:
    failed = False
    for label, kw in CONFIGS:
        for seed in SEEDS:
            r = run_movement_checks(180.0, seed=seed, **kw)
            bad = rule_violations(r)
            failed |= bool(bad)
            still_open = {k: r[k] for k in sorted(OPEN_RULES)}
            print(f"{label}, seed {seed}: {'PASS' if not bad else 'FAIL'} {r}  (open, not enforced: {still_open})")
    r4 = run_forced_collision()
    failed |= r4.startswith("FAIL")
    print("R4 forced car-pedestrian collision:", r4)
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
