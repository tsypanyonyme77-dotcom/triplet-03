"""A closed street: cars parked on it or heading for a bay on it find no route, and the engine goes on."""
import random

from twin.engine.routing import build_turn_graph, route_between
from twin.world import scenarios
from twin.world.map import build_two_blocks_graph
from twin.world.scenarios import CityParams


def _open_turns(*closed):
    turns = build_turn_graph(build_two_blocks_graph())
    turns.remove_nodes_from(closed)
    return turns


def test_no_route_starts_or_ends_on_a_closed_street():
    assert route_between(_open_turns((6, 5)), (6, 5), 10.0, (1, 2), 40.0, 5.0) is None
    assert route_between(_open_turns((1, 2)), (6, 5), 10.0, (1, 2), 40.0, 5.0) is None


def test_a_street_stays_closed_while_traffic_runs_on():
    sc = scenarios.build("city", seed=2, params=CityParams(cars=30, pedestrians=10, car_crash_risk=0.0, ped_hit_risk=0.0))
    sc.sim.set_road_state("closed", road_id="5-6")
    parked_there = [c for c in sc.sim.cars.values() if c.parking_spot_id and sc.sim.parking_spots[c.parking_spot_id].edge in ((5, 6), (6, 5))]
    assert parked_there
    random.seed(2)
    for _ in range(1200):  # 120 s: every parked car wants to leave at some point
        sc.step()
    assert all(c.parking_spot_id for c in parked_there)  # they could not leave
