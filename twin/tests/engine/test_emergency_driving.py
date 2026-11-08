"""Units with a siren: the shortest way, no traffic rules, and nobody hit."""
import math

import pytest

from twin.engine.car_collisions import body_corners, overlap_depth
from twin.engine.emergency_driving import CENTRE_LINE_SHIFT_M, RED_CROSS_MS
from twin.engine.routing import route_length
from twin.world import scenarios
from twin.world.scenarios import CityParams


def _dispatch_when_called(sc, kinds=("ambulance", "police"), seconds=120.0):
    """Runs until the first incident, then sends the units. Returns when they were sent."""
    for _ in range(int(seconds * 10)):
        sc.step()
        if sc.sim.call_centre.incidents and sc.sim.accidents:
            for kind in kinds:
                assert sc.sim.dispatch_unit(kind, sc.sim.call_centre.incidents[0]["id"])["status"] == "dispatched"
            return sc.sim._sim_time
    raise AssertionError("nobody called it in")


def test_a_unit_takes_the_shorter_way_round_to_a_wreck_from_either_end_of_its_street():
    sim = scenarios.build("city", seed=1, params=CityParams(0, 0, 0.0, 0.0)).sim
    # the fire truck's way to a spot near node 3 on the south street, driving west: right round the block
    one_way = sim._best_unit("fire", (3, 2), 10.0)
    forward = sim.scene_targets((3, 2), 10.0)
    assert forward == [((3, 2), 10.0), ((2, 3), 70.0)]
    assert one_way[0].kind == "fire"
    routes = [one_way[1], one_way[1]]
    assert routes[0][-2:] in ([3, 2], [2, 3])
    start = (one_way[0].route_nodes[0], one_way[0].route_nodes[1])
    from twin.engine.routing import route_between
    only_lane = route_between(sim._turns, start, one_way[0].dist_on_edge, (3, 2), 10.0, 10.0)
    assert one_way[2] <= route_length(sim.graph, only_lane, one_way[0].dist_on_edge, 10.0)


def test_a_responding_unit_ignores_signals_and_stops_doing_so_when_it_arrives():
    sim = scenarios.build("city", seed=1, params=CityParams(0, 0, 0.0, 0.0)).sim
    unit = next(iter(sim.units.values()))
    assert unit.obeys_signals and not unit.responding
    unit.siren, unit.status, unit.finished = True, "dispatched", False
    assert unit.responding and not unit.obeys_signals and not unit.respects_junctions
    unit.status = "on_scene"
    assert not unit.responding and unit.obeys_signals


def test_a_unit_runs_a_red_light_slowly_and_gets_there():
    sc = scenarios.build("ped-hit")
    sent = _dispatch_when_called(sc, kinds=("police",))
    sim = sc.sim
    unit = next(u for u in sim.units.values() if u.kind == "police")
    crossed_red = fastest_on_red = 0.0
    for _ in range(900):
        sc.step()
        if not unit.responding:
            break
        u, v = unit.route_nodes[unit.edge_index], unit.route_nodes[unit.edge_index + 1]
        to_line = sim.edge_length(u, v) - sim._stop_setback(u, v) - unit.dist_on_edge
        if sim._light_state(u, v) == "red" and -0.5 < to_line < 0.5:
            crossed_red += 1
            fastest_on_red = max(fastest_on_red, unit.speed)
    assert unit.status == "on_scene"
    assert sim._sim_time - sent < 45.0
    if crossed_red:
        assert fastest_on_red <= RED_CROSS_MS + 0.5


def test_a_unit_drives_past_a_queue_on_the_centre_line():
    sc = scenarios.build("city", seed=4, params=CityParams(47, 60, 0.0, 0.0))
    for _ in range(600):
        sc.step()
    sim = sc.sim
    sim.call_centre.receive(sim._sim_time, "test", "pedestrian", {"x": 160.0, "y": 40.0, "category": "medical", "confidence": 0.9}, None)
    incident = sim.call_centre.incidents[0]["id"]
    assert sim.dispatch_unit("ambulance", incident)["status"] == "dispatched"
    unit = next(u for u in sim.units.values() if u.kind == "ambulance")
    shifted = 0
    for _ in range(1200):
        sc.step()
        if unit.status != "dispatched":
            break
        shifted += unit.lateral_offset <= -CENTRE_LINE_SHIFT_M + 0.01
    assert unit.status == "on_scene", (unit.x, unit.y, unit.speed)
    assert shifted > 0


def test_cars_keep_out_of_a_junction_a_unit_has_claimed():
    sim = scenarios.build("city", seed=1, params=CityParams(0, 0, 0.0, 0.0)).sim
    sim._boxes.set_claims({"amb1": (1, 2, 3)})
    assert not sim._boxes.may_enter((5, 2, 3))             # crosses the claimed movement
    assert sim._boxes.may_enter((5, 2, 3), ignore_claims=True)
    sim._boxes.set_claims({})
    assert sim._boxes.may_enter((5, 2, 3))


@pytest.mark.parametrize("params", [CityParams(20, 40, 0.0, 1.0)])
def test_a_unit_never_hits_anyone(params):
    """Pedestrians who ignore every signal, in traffic: over several seeds, nobody is hit by a unit."""
    for seed in (1, 2):
        sc = scenarios.build("city", seed, params)
        sim = sc.sim
        sent = False
        for _ in range(2000):
            sc.step()
            if not sent and sim.accidents and sim.call_centre.incidents:
                sent = True
                for kind in ("ambulance", "police"):
                    sim.dispatch_unit(kind, sim.call_centre.incidents[0]["id"])
        assert not [a for a in sim.accidents if a["car_id"] in sim.units], seed


def test_units_do_not_drive_through_cars_on_their_way():
    for name, seed in (("ped-hit", None), ("car-crash", None), ("car-crash", 8)):
        sc = scenarios.build(name, seed)
        _dispatch_when_called(sc)
        sim, worst = sc.sim, 0.0
        for _ in range(1500):
            sc.step()
            for unit in sim.units.values():
                if not unit.responding:
                    continue
                body = body_corners(unit.x, unit.y, unit.heading, unit.params.length)
                for car in sim.cars.values():
                    if not car.finished and math.hypot(car.x - unit.x, car.y - unit.y) < 8.0:
                        worst = max(worst, overlap_depth(body, body_corners(car.x, car.y, car.heading, car.params.length)))
        assert worst < 0.3, (name, seed, worst)


def test_a_dispatch_to_an_accident_without_a_civilian_car_still_sends_the_unit():
    sc = scenarios.build("ped-hit")
    _dispatch_when_called(sc, kinds=("police",))
    sim = sc.sim
    response = next(iter(sim.responses.values()))
    accident = sim._open_accident(response["accident_id"])
    accident["car_id"] = "amb1"  # what a unit in an accident looks like: not in sim.cars
    assert sim.dispatch_unit("ambulance", response["incident_id"])["status"] == "dispatched"
