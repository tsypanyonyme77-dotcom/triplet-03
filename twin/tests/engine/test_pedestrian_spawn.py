"""Pedestrians start spread out on the sidewalks, never stacked on a shared node."""
import math

from tools.check_rules import BODY_DIAMETER_M, on_asphalt_outside_crosswalk, past_building_line
from twin.world.scenario import build_simulation


def test_a_crowd_spawns_without_overlapping_and_on_the_sidewalks():
    sim = build_simulation(cars=0, pedestrians=100, runners=0, seed=7)
    peds = list(sim.pedestrians.values())
    assert len(peds) == 100
    closest = min(math.hypot(a.x - b.x, a.y - b.y) for i, a in enumerate(peds) for b in peds[i + 1:])
    assert closest >= BODY_DIAMETER_M, closest
    assert not [p.id for p in peds if on_asphalt_outside_crosswalk(p.x, p.y) or past_building_line(p.x, p.y)]


def test_spawned_pedestrians_can_start_trips():
    """A decision gives each a route (walking or waiting at a kerb) or, when the random place
    is where they already stand, a scheduled departure; most of them walk."""
    sim = build_simulation(cars=0, pedestrians=30, runners=0, seed=3)
    for ped in sim.pedestrians.values():
        sim.apply_pedestrian_decision(ped.id, None)
    on_the_way = [p for p in sim.pedestrians.values() if p.status in ("walking", "waiting")]
    assert all(p.status in ("walking", "waiting") or p.depart_at is not None for p in sim.pedestrians.values())
    assert len(on_the_way) >= 20, len(on_the_way)


def test_a_trip_starts_at_the_end_of_the_sidewalk_piece_toward_the_destination():
    sim = build_simulation(cars=0, pedestrians=1, runners=0, seed=3)
    ped = next(iter(sim.pedestrians.values()))
    a, b = ped.spawn_piece
    ax, ay = sim.walk.xy(a)
    bx, by = sim.walk.xy(b)
    ped.force.x, ped.force.y = (ax * 3 + bx) / 4, (ay * 3 + by) / 4  # a quarter of the way from a to b
    ped.route_nodes = [a]
    # a destination on the b side: the trip starts at b, not at the nearer a, so no walking back
    sim._walk_to_node(ped, b)
    assert ped.route_nodes[0] == b or ped.status == "arrived"  # b itself is the destination: dwell
    ped.spawn_piece = (a, b)
    ped.route_nodes, ped.status, ped.finished, ped.depart_at = [a], "arrived", True, None
    assert sim._trip_start_node(ped, b) == b
    assert ped.spawn_piece is None  # only the first trip is special
