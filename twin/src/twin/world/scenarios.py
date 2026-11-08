"""Named, scripted scenarios on the two-block map, for recordings, demos and tests.

Each scenario is ordinary random traffic (scenario.build_simulation) plus a script
called before every tick that stages one event deterministically, by watching
the actors (positions, speeds, lights) rather than by fixed times, so it still
lines up if traffic delays the actors a little.

  city      the default: random traffic sized and made risky by CityParams; accidents
            happen on their own, with a chance set by car_crash_risk and ped_hit_risk
  ped-hit   a careless driver (does not yield) and a distracted pedestrian who
            steps onto crosswalk cw_2_1 against the light: the car hits them on
            the crosswalk; nothing is dispatched, the accident waits for a call
  car-crash a driver runs the red light coming south into node 2 and hits the
            side of a car crossing westbound on green; both cars stop where
            they are; nothing is dispatched, the accident waits for a call
  building-fire
            a building on the south street catches fire at 10 s; it burns, and
            spreads to the buildings next to it, until a fire truck is called
  flood     a cloudburst fills the dip of street 2-3; careful drivers stop driving
            into it, and a driver who ignores the water stalls in it with the
            driver stranded; nothing is dispatched, the incident waits for a call

Usage: scenario = build("ped-hit"); scenario.step() each tick (see record.py).
"""
from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from typing import Any

import twin.engine.sim as sim_module
from twin.engine.flood import RainProfile
from twin.engine.pedestrian import Pedestrian
from twin.engine.social_force import SocialForceState
from twin.world.scenario import DT, build_simulation, step

Script = Callable[[sim_module.Simulation], None]


@dataclass
class Scenario:
    name: str
    sim: sim_module.Simulation
    script: Script = field(default=lambda sim: None)
    # ids of the staged actors, for tests and the recorder's summary
    actors: dict[str, str] = field(default_factory=dict)
    # chooses the places road users go to (twin.engine.decision.Decider); None = random places
    decider: Any = None

    def step(self) -> None:
        self.script(self.sim)
        step(self.sim, self.decider)


MAX_CARS = 47  # the map has 56 parking spots, 3 of them station bays; with every spot taken no car finds a free one and none drives
MAX_PEDESTRIANS = 100
RUNNER_SHARE = 0.1


@dataclass(frozen=True)
class CityParams:
    """The default city. The risks are per road user, see scenario.build_simulation."""
    cars: int = 20
    pedestrians: int = 40
    car_crash_risk: float = 0.1
    ped_hit_risk: float = 0.1
    fire_risk: float = 0.0      # per building: the chance it catches fire once, in the first few minutes
    flood_risk: float = 0.0     # per street: the chance its drain blocks and a downpour floods it, once

    def __post_init__(self) -> None:
        if not 0 <= self.cars <= MAX_CARS:
            raise ValueError(f"cars must be between 0 and {MAX_CARS}, got {self.cars}")
        if not 0 <= self.pedestrians <= MAX_PEDESTRIANS:
            raise ValueError(f"pedestrians must be between 0 and {MAX_PEDESTRIANS}, got {self.pedestrians}")
        for name in ("car_crash_risk", "ped_hit_risk", "fire_risk", "flood_risk"):
            if not 0.0 <= getattr(self, name) <= 1.0:
                raise ValueError(f"{name} must be between 0 and 1, got {getattr(self, name)}")

    def clean(self) -> "CityParams":
        """The same traffic with nobody reckless."""
        return replace(self, car_crash_risk=0.0, ped_hit_risk=0.0, fire_risk=0.0, flood_risk=0.0)

    def as_dict(self) -> dict[str, float]:
        return asdict(self)


def _city(seed: int = 7, params: CityParams | None = None) -> Scenario:
    params = params or CityParams()
    return Scenario("city", build_simulation(
        cars=params.cars, pedestrians=params.pedestrians, runners=round(params.pedestrians * RUNNER_SHARE), seed=seed,
        car_crash_risk=params.car_crash_risk, ped_hit_risk=params.ped_hit_risk, fire_risk=params.fire_risk,
        building_places=True,
        flood_risk=params.flood_risk,
    ))


def _road_clear(sim: sim_module.Simulation, edges: list[tuple[int, int]], ahead_m: float = 30.0) -> bool:
    """No moving vehicle on the first edge, nor within `ahead_m` of the start of the
    others: a staged car must not be slowed down by traffic in front of it."""
    for vehicle in sim._moving_vehicles():
        u, v = vehicle.route_nodes[vehicle.edge_index], vehicle.route_nodes[vehicle.edge_index + 1]
        for i, edge in enumerate(edges):
            if (u, v) == edge and (i == 0 or vehicle.dist_on_edge - vehicle.params.length < ahead_m):
                return False
    return True


def _spots_on(sim: sim_module.Simulation, edge: tuple[int, int]) -> list:
    """Free parking spots along `edge`, in driving order."""
    spots = [sp for sp in sim.parking_spots.values() if sp.edge == edge and sp.occupied_by is None]
    return sorted(spots, key=lambda sp: sp.dist_on_edge)


def _stage_car(sim: sim_module.Simulation, car_id: str, start_edge: tuple[int, int], dest_edge: tuple[int, int]):
    """A staged car parked at the first free spot of `start_edge` (furthest upstream), with
    the last free spot of `dest_edge` reserved for it. It waits there until the script
    calls sim.start_trip(car, dest, force=True): no car ever appears mid-street."""
    car = sim.spawn_parked_car(_spots_on(sim, start_edge)[0].id, car_id=car_id)
    dest = _spots_on(sim, dest_edge)[-1]
    dest.occupied_by = car.id
    return car, dest.id


def _about_to_turn_green(sim: sim_module.Simulation, node: int, approach: int, within_s: float) -> bool:
    light = sim.traffic_lights[node]
    return light.state_for_approach(approach) == "red" and light.seconds_until_change(approach) <= within_s


def _eta(distance: float, speed: float, accel: float) -> float:
    """Seconds to cover `distance` at the current speed and (non-negative) acceleration."""
    if distance <= 0:
        return 0.0
    a = max(accel, 0.0)
    if a < 1e-6:
        return distance / max(speed, 0.1)
    return (-speed + math.sqrt(speed * speed + 2 * a * distance)) / a


# ---- ped-hit ------------------------------------------------------------------

HIT_CAR_ID = "careless_car"
HIT_PED_ID = "distracted_ped"
HIT_NODE, HIT_ARM = 2, 1          # crosswalk cw_2_1: across the west arm of node 2, x = 70
HIT_WARMUP_S = 15.0               # let the background traffic spread out first
HIT_DEPART_BEFORE_GREEN_S = 5.0   # pull out at most this long before the west-east green: from rest it reaches the stop line 3-8 s into it
HIT_PED_LEAD_S = 6.4              # release the pedestrian when the car is this far (in time) from the impact point:
                                  # tuned so the pedestrian is near the lane centre when the bonnet arrives
HIT_IMPACT_AHEAD_M = 2.0          # aim for the car's front this far past the crosswalk centre (mid-bonnet)


def _ped_hit(seed: int = 7) -> Scenario:
    # default seed 7: witnesses are random and this background is light, and a call starts the whole
    # response; here the first call comes 1.5 s after the hit (with 5, the old default, none in 120 s)
    sim = build_simulation(cars=3, pedestrians=4, runners=1, distracted=0, seed=seed)
    cw = sim.walk.crosswalk_at(HIT_NODE, HIT_ARM)
    # start on the south kerb, so the first lane crossed is the eastbound one
    south, north = sorted((cw.a, cw.b), key=lambda n: sim.walk.xy(n)[1])
    sx, sy = sim.walk.xy(south)
    ped = Pedestrian(
        id=HIT_PED_ID,
        route_nodes=[south, north],
        force=SocialForceState(x=sx, y=sy),
        status="arrived",  # stands at the kerb until the script sends it
        finished=True,
        loop=False,
        distracted=True,
    )
    sim.pedestrians[ped.id] = ped
    crosswalk_x = sim.walk.xy(south)[0]
    car, dest = _stage_car(sim, HIT_CAR_ID, (HIT_ARM, HIT_NODE), (HIT_NODE, 3))  # parked on y = 0 heading east
    car.yield_to_pedestrians = False
    car.respects_junctions = False  # a careless driver does not wait for the junction: its timing stays as staged
    state = {"started": False, "released": False}

    def script(s: sim_module.Simulation) -> None:
        if not state["started"]:
            ready = (
                s._sim_time >= HIT_WARMUP_S
                and _about_to_turn_green(s, HIT_NODE, HIT_ARM, HIT_DEPART_BEFORE_GREEN_S)
                and _road_clear(s, [(HIT_ARM, HIT_NODE), (HIT_NODE, 3)])
            )
            if ready:
                state["started"] = s.start_trip(car, dest, force=True)
            return
        if state["released"] or car.status != "driving":
            return
        if _eta(crosswalk_x + HIT_IMPACT_AHEAD_M - car.x, car.speed, car.accel) <= HIT_PED_LEAD_S:
            ped.status, ped.finished = "walking", False  # distracted: steps out without looking
            state["released"] = True

    return Scenario("ped-hit", sim, script, {"car": HIT_CAR_ID, "pedestrian": HIT_PED_ID})


# ---- car-crash ----------------------------------------------------------------

CRASH_RUNNER_ID = "red_light_runner"
CRASH_VICTIM_ID = "crossing_car"
CRASH_NODE = 2
CRASH_RUNNER_FROM, CRASH_RUNNER_TO = 5, 3     # southbound into node 2, then left (east)
CRASH_VICTIM_FROM, CRASH_VICTIM_TO = 3, 1     # westbound straight through node 2, on y = +2.5
CRASH_WARMUP_S = 15.0
CRASH_DEPART_BEFORE_GREEN_S = 5.0  # as for ped-hit: the victim reaches node 2 inside its green, the runner's approach is red
# Both cars pull out of the first spot of their street; the runner pulls out this much
# later. Tuned by a sweep over background seeds 1-10: 0.6 s gives a T-bone (the runner's
# front in the victim's lane, at about (79, 2.7)) on 9 of 10; at 0 s the victim drives
# into the runner's side instead, from 0.9 s on the victim is often already past.
CRASH_RUNNER_DELAY_S = 0.6


def _clear_ahead(sim: sim_module.Simulation, car, edges: list[tuple[int, int]], ahead_m: float = 30.0) -> bool:
    """No moving vehicle in front of the parked `car` on its street (cars behind just follow
    it), nor within `ahead_m` of the start of the next streets on its way."""
    for vehicle in sim._moving_vehicles():
        u, v = vehicle.route_nodes[vehicle.edge_index], vehicle.route_nodes[vehicle.edge_index + 1]
        if (u, v) == edges[0] and vehicle.dist_on_edge > car.dist_on_edge - vehicle.params.length:
            return False
        if (u, v) in edges[1:] and vehicle.dist_on_edge - vehicle.params.length < ahead_m:
            return False
    return True


def _crosswalk_quiet(sim: sim_module.Simulation, node: int, arm: int, radius_m: float = 8.0) -> bool:
    """Nobody on the crosswalk or near either end of it. The runner crosses cw_2_5 while
    pedestrians there have their turn; this keeps the staged event a car-car crash."""
    cw = sim.walk.crosswalk_at(node, arm)
    ends = [sim.walk.xy(cw.a), sim.walk.xy(cw.b)]
    mid = ((ends[0][0] + ends[1][0]) / 2, (ends[0][1] + ends[1][1]) / 2)
    return not any(
        math.hypot(p.x - x, p.y - y) < radius_m
        for p in sim.pedestrians.values()
        for x, y in ends + [mid]
    )


def _car_crash(seed: int = 4) -> Scenario:
    # default seed 4 (was 2 before the stations took 3 bays): with 2 a background car now follows
    # the runner into node 2 and is trapped behind the wreck past its stop line (R3, R5)
    # light background: on this small map more traffic almost always queues on one of the
    # staged cars' streets or waits at cw_2_5 when the window comes
    sim = build_simulation(cars=2, pedestrians=2, runners=1, distracted=0, seed=seed)
    victim, victim_dest = _stage_car(sim, CRASH_VICTIM_ID, (CRASH_VICTIM_FROM, CRASH_NODE), (CRASH_NODE, CRASH_VICTIM_TO))
    runner, runner_dest = _stage_car(sim, CRASH_RUNNER_ID, (CRASH_RUNNER_FROM, CRASH_NODE), (CRASH_NODE, CRASH_RUNNER_TO))
    runner.obeys_signals = False          # runs the red at node 2
    runner.yield_to_pedestrians = False   # and does not look out for anyone else either
    runner.slows_for_turns = False        # nor slow down for the corner
    state = {"victim": False, "runner": False, "victim_left_at": 0.0}

    def script(s: sim_module.Simulation) -> None:
        if state["runner"]:
            return
        if not state["victim"]:
            ready = (
                s._sim_time >= CRASH_WARMUP_S
                and _about_to_turn_green(s, CRASH_NODE, CRASH_VICTIM_FROM, CRASH_DEPART_BEFORE_GREEN_S)
                and _clear_ahead(s, victim, [(CRASH_VICTIM_FROM, CRASH_NODE), (CRASH_NODE, CRASH_VICTIM_TO)])
                and _clear_ahead(s, runner, [(CRASH_RUNNER_FROM, CRASH_NODE), (CRASH_NODE, CRASH_RUNNER_TO)])
                and _crosswalk_quiet(s, CRASH_NODE, CRASH_RUNNER_FROM)
                and s._can_pull_out(runner)
            )
            if ready:
                state["victim"] = s.start_trip(victim, victim_dest, force=True)
                state["victim_left_at"] = s._sim_time
            return
        if s._sim_time - state["victim_left_at"] >= CRASH_RUNNER_DELAY_S - 1e-9:
            state["runner"] = s.start_trip(runner, runner_dest, force=True)

    return Scenario("car-crash", sim, script, {"striking": CRASH_RUNNER_ID, "struck": CRASH_VICTIM_ID})


# ---- building-fire ------------------------------------------------------------

FIRE_BUILDING_ID = "bld-01-03"   # block A, on the south street, 47 m from the camera at node 2
FIRE_START_S = 10.0              # let the background traffic spread out first


def _building_fire(seed: int = 7) -> Scenario:
    """A building catches fire. Nothing else is staged: the smoke sensor, the camera, the witnesses on the
    street, the drivers and pedestrians who keep away, the truck that is called and puts it out, and the
    fire spreading to the buildings next to it if the truck is late, all come from the engine."""
    sim = build_simulation(cars=6, pedestrians=12, runners=1, distracted=0, seed=seed)
    state = {"started": False}

    def script(s: sim_module.Simulation) -> None:
        if not state["started"] and s._sim_time >= FIRE_START_S:
            state["started"] = s.ignite_building(FIRE_BUILDING_ID, cause="scenario")["status"] == "ignited"

    return Scenario("building-fire", sim, script, {"building": FIRE_BUILDING_ID})


# ---- flood ---------------------------------------------------------------------

FLOOD_DRIVER_ID = "flood_driver"
FLOOD_FROM, FLOOD_THROUGH, FLOOD_TO = (6, 3), (3, 2), (2, 1)  # south on the east street, right into 3-2, west through the dip
# a cloudburst: dry for 10 s, 120 mm/h from t = 30 to t = 150 s, dry again at t = 180 s
FLOOD_RAIN = RainProfile(((10.0, 0.0), (30.0, 120.0), (150.0, 120.0), (180.0, 0.0)))
# the driver sets off once the low point is this deep: by the time they reach it the water
# is past the stall depth (flood.STALL_DEPTH_M), well before they reach the low point
FLOOD_RELEASE_DEPTH_M = 0.27
FLOOD_WALKER_ID = "flood_walker"
# the walker sets off along the north sidewalk of street 2-3 once the low point is this deep. At its
# deepest the sidewalk is under the low point's depth less the kerb, so they wade in and are trapped
# (flood.PED_TRAP_DEPTH_M) a few metres before the low point
FLOOD_WALKER_RELEASE_DEPTH_M = 0.33


def _flood(seed: int = 3) -> Scenario:
    sim = build_simulation(cars=6, pedestrians=10, runners=1, distracted=0, seed=seed)
    zone = sim.flood_zones[0]  # dip-2-3
    zone.rain = FLOOD_RAIN     # over this street only: the drain works, it just cannot keep up
    car, dest = _stage_car(sim, FLOOD_DRIVER_ID, FLOOD_FROM, FLOOD_TO)
    car.ignores_flood = True  # drives into the water the careful drivers stay out of
    walker = _stage_flood_walker(sim, zone)
    state = {"started": False}

    def script(s: sim_module.Simulation) -> None:
        if walker.finished and walker.status == "arrived" and zone.depth_m >= FLOOD_WALKER_RELEASE_DEPTH_M:
            walker.status, walker.finished = "walking", False  # does not look at the water
        if state["started"] or zone.depth_m < FLOOD_RELEASE_DEPTH_M:
            return
        if _clear_ahead(s, car, [FLOOD_FROM, FLOOD_THROUGH]):
            state["started"] = s.start_trip(car, dest, force=True)

    return Scenario("flood", sim, script, {"car": FLOOD_DRIVER_ID, "pedestrian": FLOOD_WALKER_ID, "flood_zone": zone.id})


def _stage_flood_walker(sim: sim_module.Simulation, zone) -> Pedestrian:
    """A pedestrian who ignores the water, standing at the west end of the north sidewalk of the
    flooded street, with a walk along all of it."""
    side_y = zone.ay + zone.road_half_width_m + zone.sidewalk_width_m / 2
    nodes = sorted((n for n in sim.walk.graph.nodes
                    if abs(sim.walk.xy(n)[1] - side_y) < 0.5 and zone.ax < sim.walk.xy(n)[0] < zone.bx),
                   key=lambda n: sim.walk.xy(n)[0])
    x, y = sim.walk.xy(nodes[0])
    walker = Pedestrian(id=FLOOD_WALKER_ID, route_nodes=nodes, force=SocialForceState(x=x, y=y),
                        status="arrived", finished=True, loop=False, ignores_flood=True)
    sim.pedestrians[walker.id] = walker
    return walker


SCENARIOS: dict[str, Callable[..., Scenario]] = {
    "city": _city,
    "ped-hit": _ped_hit,
    "car-crash": _car_crash,
    "building-fire": _building_fire,
    "flood": _flood,
}


def build(name: str, seed: int | None = None, params: CityParams | None = None) -> Scenario:
    """`seed` changes the background traffic only; the staged event adapts to it. `params` sizes
    the city scenario; the staged scenarios (ped-hit, car-crash, building-fire, flood) always stage exactly
    their one event on a light, clean background."""
    if name not in SCENARIOS:
        raise ValueError(f"unknown scenario {name!r}; one of {', '.join(SCENARIOS)}")
    kwargs = {"params": params} if name == "city" else {}
    return SCENARIOS[name](**({} if seed is None else {"seed": seed}), **kwargs)


def run(name: str, seconds: float, seed: int | None = None, params: CityParams | None = None) -> Scenario:
    scenario = build(name, seed, params)
    for _ in range(round(seconds / DT)):
        scenario.step()
    return scenario


if __name__ == "__main__":
    import sys

    name = sys.argv[1] if len(sys.argv) > 1 else "ped-hit"
    seeds = [int(x) for x in sys.argv[2:]] or [None]
    for seed in seeds:
        sc = run(name, 90.0, seed)
        print(f"seed {seed}:", [
            (a["kind"], a["t"], a["x"], a["y"], a["car_id"], a["pedestrian_id"] or a.get("other_car_id"), a["cleared_t"])
            for a in sc.sim.accidents
        ])
