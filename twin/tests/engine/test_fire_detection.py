"""How the city finds out about a building fire: its smoke sensor, and witnesses who call it in."""
import math

from twin.engine.fires import SMOKE_AT, RAMP_S, FireModel
from twin.engine.pedestrian import Pedestrian
from twin.engine.social_force import SocialForceState
from twin.world.scenario import DT, build_simulation


def _quiet_city():
    return build_simulation(cars=0, pedestrians=0)


def _run(sim, seconds: float) -> None:
    for _ in range(round(seconds / DT)):
        sim.tick(DT)


def test_the_smoke_sensor_trips_seconds_after_ignition_and_opens_an_incident():
    sim = _quiet_city()
    sim.ignite_building("bld-01-01")
    _run(sim, 2.0)
    assert sim.fire.get("fire-0001")["incident_id"] is None             # not yet
    _run(sim, 2.0)
    fire = sim.fire.get("fire-0001")
    assert fire["incident_id"] == "inc-0001" and abs(fire["smoke_t"] - SMOKE_AT * RAMP_S) < 0.6
    event = next(e for e in sim.timeline if e["kind"] == "smoke_detected")
    assert event["incident_id"] == "inc-0001" and event["building_id"] == "bld-01-01"
    assert sim.call_centre.incident("inc-0001")["x"] == fire["x"]


def test_a_second_fire_next_door_joins_the_same_incident_and_one_far_away_gets_its_own():
    sim = _quiet_city()
    sim.ignite_building("bld-01-01")
    sim.ignite_building(sim.fire.next_to["bld-01-01"][0])
    sim.ignite_building("bld-02-06")
    _run(sim, 5.0)
    ids = {f["building_id"]: f["incident_id"] for f in sim.fire.open()}
    assert ids["bld-01-01"] == ids[sim.fire.next_to["bld-01-01"][0]] == "inc-0001"
    assert ids["bld-02-06"] == "inc-0002"


def test_sensor_values_rise_with_the_fire():
    low, high = FireModel.sensor_values(0.05), FireModel.sensor_values(1.0)
    assert not low["smoke_detected"] and high["smoke_detected"]
    assert low["temp_c"] < 50 < 300 < high["temp_c"] <= 400
    assert 420 <= low["co2_ppm"] < 1000 < 4000 < high["co2_ppm"] <= 5000


def test_a_camera_sees_the_smoke_only_of_a_strong_enough_fire_close_by():
    sim = _quiet_city()
    cam = sim.cameras[0]
    assert not sim.smoke_near(cam.x, cam.y)
    sim.ignite_building("bld-01-01")
    _run(sim, 1.0)
    assert not sim.smoke_near(cam.x, cam.y)                  # still too weak
    _run(sim, 5.0)
    front = sim.fire.buildings["bld-01-01"].front
    assert sim.smoke_near(*front)
    assert sim.smoke_near(cam.x, cam.y) == (math.hypot(cam.x - front[0], cam.y - front[1]) <= 60.0)
    assert not sim.smoke_near(front[0] + 500.0, front[1])    # too far


def _stand_near(sim, building_id: str, ped_id: str, distance_m: float = 6.0) -> Pedestrian:
    """A pedestrian dwelling on the sidewalk `distance_m` along the street from the building's front."""
    front = sim.fire.buildings[building_id].front
    x, y = front
    # the building faces a street running along x or y: step along the street, staying in the corridor
    on_x = front[1] in (11.5, 80.0 - 11.5)
    x, y = (x + distance_m, y) if on_x else (x, y + distance_m)
    ped = Pedestrian(id=ped_id, route_nodes=[0], force=SocialForceState(x=x, y=y), status="arrived", finished=True, loop=False)
    sim.pedestrians[ped_id] = ped
    return ped


def test_witnesses_call_a_fire_in_as_a_fire_and_the_call_joins_the_sensors_incident():
    callers = fire_calls = 0
    for seed in range(1, 9):                                 # each one calls with probability 1/2
        sim = build_simulation(cars=0, pedestrians=0, seed=seed)
        for i in range(6):
            _stand_near(sim, "bld-01-01", f"watcher{i}", distance_m=4.0 + 2 * i)
        sim.ignite_building("bld-01-01")
        _run(sim, 40.0)
        calls = sim.call_centre.calls
        callers += len(calls)
        fire_calls += sum(c["category"] == "fire" for c in calls)
        for call in calls:
            assert call["category"] in ("fire", "medical", "police", "flood", "other")   # a caller can be wrong
            assert call["truth_accident_id"] == "fire-0001"
            assert call["incident_id"] == "inc-0001"
            assert call["t"] >= 6.0 - 1e-6                    # nobody calls before the flames are visible
        assert len(sim.call_centre.incidents) == 1
    assert callers >= 5 and fire_calls >= 0.7 * callers      # a caller gets the category wrong 1 time in 10
