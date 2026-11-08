"""Cars live in parking spots: spawn there, drive spot to spot, pull out and in on a steered path."""
import itertools
import math

import pytest

from twin.engine.car_collisions import body_corners, overlap_depth
from twin.engine.parking import SPOT_LENGTH_M, spot_world_xy
from twin.engine.routing import build_turn_graph, route_between
from twin.engine.street_profile import PARKING_LANE_M
from twin.world.map import build_two_blocks_graph
from twin.world.scenario import DT, build_simulation, step


def test_spawned_cars_stand_in_distinct_spots_without_touching():
    sim = build_simulation(cars=15, pedestrians=0, runners=0, seed=11)
    cars = list(sim.cars.values())
    assert all(c.status == "parked" and c.parking_spot_id for c in cars)
    assert len({c.parking_spot_id for c in cars}) == len(cars)
    for a, b in itertools.combinations(cars, 2):
        depth = overlap_depth(body_corners(a.x, a.y, a.heading, 4.5), body_corners(b.x, b.y, b.heading, 4.5))
        assert depth < 0, (a.id, b.id)


def test_routes_never_u_turn():
    road = build_two_blocks_graph()
    turns = build_turn_graph(road)
    edges = list(turns.nodes)
    for start, dest in itertools.product(edges, edges):
        route = route_between(turns, start, 20.0, dest, 40.0, 22.0)
        assert route is not None
        assert route[:2] == list(start) and route[-2:] == list(dest)
        assert all(a != c for a, c in zip(route, route[2:])), route


def test_a_trip_pulls_out_drives_and_parks_in_the_reserved_spot():
    sim = build_simulation(cars=0, pedestrians=0, runners=0, seed=3)
    car = sim.spawn_parked_car("1_2_0", car_id="c")
    start = (car.x, car.y, car.heading)
    assert sim.start_trip(car, "2_3_3", force=True)
    lateral_max, prev = 0.0, (car.x, car.y)
    for _ in range(int(60 / DT)):
        step(sim)
        lateral_max = max(lateral_max, abs(car.y - start[1]))
        assert math.hypot(car.x - prev[0], car.y - prev[1]) < 2.0  # no jump
        prev = (car.x, car.y)
        if car.status == "parked":
            break
    assert car.status == "parked" and car.parking_spot_id == "2_3_3"
    assert sim.parking_spots["2_3_3"].occupied_by == "c"
    assert sim.parking_spots["1_2_0"].occupied_by is None  # the spot left behind is free again
    assert lateral_max > 3.5  # it really pulled out from the parking lane (4 m from the lane centre) and back in
    assert abs(car.y - start[1]) < 0.5  # parked on the same kerb line (y = -6.5) further east


def test_parking_geometry_gives_each_bay_its_size_for_drawing():
    spots = build_simulation(cars=0, pedestrians=0, runners=0).parking_geometry()["spots"]
    assert len(spots) == 56
    assert {(s["length"], s["width"]) for s in spots} == {(SPOT_LENGTH_M, PARKING_LANE_M)}


def _park_between_neighbours(origin: str, dest: str, neighbours: tuple[str, ...]) -> dict:
    """Drives one car from `origin` into `dest` with `neighbours` parked: final pose in the
    bay (heading error, sideways and lengthwise offset of the body centre) and the deepest
    overlap with a parked car on the way."""
    sim = build_simulation(cars=0, pedestrians=0, runners=0, seed=3)
    car = sim.spawn_parked_car(origin, car_id="c")
    parked = [sim.spawn_parked_car(n, car_id=f"p{i}") for i, n in enumerate(neighbours)]
    assert sim.start_trip(car, dest, force=True)
    deepest = 0.0
    for _ in range(int(120 / DT)):
        step(sim)
        mine = body_corners(car.x, car.y, car.heading, car.params.length)
        for p in parked:
            deepest = max(deepest, overlap_depth(mine, body_corners(p.x, p.y, p.heading, p.params.length)))
        if car.status == "parked":
            break
    sx, sy, sh = spot_world_xy(sim.graph, sim.parking_spots[dest], 0.0)
    cx = car.x - math.cos(car.heading) * car.params.length / 2
    cy = car.y - math.sin(car.heading) * car.params.length / 2
    return {
        "status": car.status,
        "heading_deg": math.degrees(math.atan2(math.sin(car.heading - sh), math.cos(car.heading - sh))),
        "sideways_m": -(cx - sx) * math.sin(sh) + (cy - sy) * math.cos(sh),
        "lengthwise_m": (cx - sx) * math.cos(sh) + (cy - sy) * math.sin(sh),
        "deepest_overlap_m": deepest,
    }


@pytest.mark.parametrize(
    "origin, dest, neighbours",
    [
        ("1_2_0", "2_3_2", ("1_2_1", "2_3_1", "2_3_3")),  # mid-street, both neighbours taken
        ("1_2_0", "2_3_0", ("1_2_1", "2_3_1")),            # first bay after a junction
        ("4_5_1", "5_6_3", ("4_5_2", "5_6_2")),            # last bay before a junction
        ("3_6_2", "5_4_1", ("3_6_3", "5_4_0", "5_4_2")),   # after a turn, both neighbours taken
        ("1_2_0", "2_5_0", ("1_2_1", "2_5_1")),            # first bay right after a left turn
        ("6_5_0", "3_6_0", ("6_5_1", "3_6_1")),            # first bay right after a right turn
    ],
)
def test_a_car_parks_straight_and_centred_without_touching_its_neighbours(origin, dest, neighbours):
    r = _park_between_neighbours(origin, dest, neighbours)
    assert r["status"] == "parked", r
    # forwards into a 7.5 m gap between parked cars the heading cannot fully settle (about 2.5 deg)
    assert abs(r["heading_deg"]) < 3.0, r
    assert abs(r["sideways_m"]) < 0.1, r
    assert abs(r["lengthwise_m"]) < 0.25, r
    assert r["deepest_overlap_m"] == 0.0, r
