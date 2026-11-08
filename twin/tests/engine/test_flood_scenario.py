"""The flood scenario: a cloudburst fills the dip of street 2-3, careful drivers stay out, one driver who
ignores the water stalls in it, and the response (fire truck, police, pump) clears it (flood_response.py)."""
import pytest

from tools.check_rules import rule_violations, run_movement_checks
from twin.engine import flood as fl
from twin.world import scenarios

DT = 0.1


def _respond(seed, pump: bool = True, delay_s: float = 8.0, limit_s: float = 1000.0, sc=None):
    """Runs the flood scenario and, delay_s after the first call, sends a fire truck and a police car (and
    starts the pump), as the City Brain would. Returns the scenario once its incident is closed."""
    sc = sc or scenarios.build("flood", seed)
    sim, act_at = sc.sim, None
    for _ in range(round(limit_s / DT)):
        sc.step()
        if act_at is None and sim.call_centre.calls:
            act_at = sim._sim_time + delay_s
        if act_at is not None and sim._sim_time >= act_at:
            incident_id = sim.call_centre.calls[0]["incident_id"]
            assert sim.dispatch_unit("fire", incident_id)["status"] == "dispatched"
            assert sim.dispatch_unit("police", incident_id)["status"] == "dispatched"
            if pump:
                assert sim.set_pump("on", incident_id=incident_id)["status"] == "on"
            act_at = float("inf")
        if sim.responses and all(r["phase"] == "closed" for r in sim.responses.values()):
            break
    return sc


def _t(sim, kind: str) -> float:
    return next(e["t"] for e in sim.timeline if e["kind"] == kind)


def test_the_rain_floods_the_street_and_traps_only_those_who_ignore_it():
    sc = scenarios.run("flood", 150.0)
    sim, zone = sc.sim, sc.sim.flood_zones[0]
    assert _t(sim, "rain_started") < _t(sim, "water_rising") < _t(sim, "street_flooded")
    assert zone.no_entry and sim.flooded_edges == {(2, 3), (3, 2)}
    assert [(a["kind"], a["car_id"] or a["pedestrian_id"]) for a in sim.accidents] == [
        ("flooded_car", sc.actors["car"]), ("trapped_pedestrian", sc.actors["pedestrian"])]
    a = sim.accidents[0]
    assert a["water_depth_m"] >= fl.STALL_DEPTH_M and 94.0 < a["x"] < 142.0 and a["cleared_t"] is None
    car = sim.cars[sc.actors["car"]]
    assert car.status == "crashed" and car.stalled and car.speed == 0.0
    assert all(c.status != "crashed" for c in sim.cars.values() if c.id != car.id)
    trapped = sim.accidents[1]
    walker = sim.pedestrians[sc.actors["pedestrian"]]
    assert trapped["water_depth_m"] >= fl.PED_TRAP_DEPTH_M and trapped["cause"] == "walked_into_flood"
    assert trapped["y"] > fl.KERB_HEIGHT_M and 94.0 < trapped["x"] < 142.0      # on the north sidewalk, in the dip
    assert walker.status == "trapped" and walker.finished
    assert [p.id for p in sim.pedestrians.values() if p.status == "trapped"] == [walker.id]


@pytest.mark.parametrize("seed", [None, 4, 10])
def test_careful_pedestrians_turn_back_before_deep_water_and_are_never_trapped(seed):
    sc = scenarios.run("flood", 250.0, seed)
    sim = sc.sim
    turned = [e for e in sim.timeline if e["kind"] == "pedestrian_turned_back"]
    assert turned and all(e["water_depth_m"] >= fl.PED_STOP_DEPTH_M for e in turned)
    assert [a["pedestrian_id"] for a in sim.accidents if a["kind"] == "trapped_pedestrian"] == [sc.actors["pedestrian"]]


def test_routes_never_walk_a_sidewalk_with_deep_water_anywhere_on_it():
    sim = scenarios.run("flood", 120.0).sim
    weight = sim._walk_weight()
    deep = [(u, v) for (u, v), d in sim._walk_edge_depths().items() if d >= fl.PED_STOP_DEPTH_M]
    assert deep                                                  # the sidewalk pieces round the low point
    for u, v in deep:
        assert weight(u, v, sim.walk.graph.edges[u, v]) is None  # mid-edge water counts, not only the nodes
    dry = next((u, v) for u, v in sim.walk.graph.edges if (u, v) not in sim._walk_edge_depths())
    assert weight(*dry, sim.walk.graph.edges[dry]) == sim.walk.graph.edges[dry]["length"]


def test_flood_calls_are_merged_into_one_incident_and_say_flood():
    sim = scenarios.run("flood", 150.0).sim
    calls = sim.call_centre.calls
    assert calls and {c["incident_id"] for c in calls} == {"inc-0001"}
    assert sum(c["category"] == "flood" for c in calls) >= len(calls) / 2   # a few callers get it wrong


def test_the_flood_scenario_keeps_the_movement_rules():
    result = run_movement_checks(150.0, scenario=scenarios.build("flood"))
    assert rule_violations(result) == {}


@pytest.mark.parametrize("seed", [2, 3])  # both deadlocked units behind cars yielding to them before the fix
def test_fire_truck_police_and_pump_rescue_the_driver_and_clear_the_street(seed):
    sc = _respond(seed)
    sim = sc.sim
    (response,) = sim.responses.values()
    assert response["phase"] == "closed", (seed, response)
    order = ["incident", "unit_dispatched", "pump_started", "rescue_started", "scene_cleared"]
    assert [_t(sim, k) for k in order] == sorted(_t(sim, k) for k in order)
    assert _t(sim, "rescue_started") < min(_t(sim, "driver_rescued"), _t(sim, "pedestrian_rescued")) <= _t(sim, "scene_cleared")
    walker = sim.pedestrians[sc.actors["pedestrian"]]
    assert walker.status != "trapped" and sim.water_depth_at(walker.x, walker.y) < fl.PED_WADE_DEPTH_M  # led out
    assert all(a["cleared_t"] is not None for a in sim.accidents)
    assert sc.actors["car"] not in sim.cars                       # towed away
    assert sim.accidents[0]["cleared_t"] is not None
    assert not sim.closed_edges                                   # the police lifted their barriers
    assert all(u.status == "idle" for u in sim.units.values())    # everyone back at the station
    assert [a["car_id"] or a["pedestrian_id"] for a in sim.accidents] == [sc.actors["car"], sc.actors["pedestrian"]]


def test_a_pedestrian_trapped_with_no_car_in_the_water_is_rescued_too():
    sc = scenarios.build("flood")
    sc.sim.cars[sc.actors["car"]].ignores_flood = False  # the driver stays out: only the walker is caught
    sim = _respond(None, sc=sc).sim
    assert [a["kind"] for a in sim.accidents] == ["trapped_pedestrian"]
    (response,) = sim.responses.values()
    assert response["phase"] == "closed" and response["accident_id"] == sim.accidents[0]["id"]
    assert _t(sim, "rescue_started") < _t(sim, "pedestrian_rescued") <= _t(sim, "scene_cleared")
    kinds = {e["kind"] for e in sim.timeline}
    assert "driver_rescued" not in kinds and "barrier_placed" in kinds   # the police still close the street


def test_without_the_pump_the_storm_drain_alone_takes_much_longer():
    with_pump, without = _respond(3), _respond(3, pump=False)
    assert without.sim.responses["inc-0001"]["phase"] == "closed"
    assert _t(without.sim, "scene_cleared") > _t(with_pump.sim, "scene_cleared") + 200.0


def test_the_pump_is_idempotent_and_found_by_id_or_incident():
    sim = scenarios.run("flood", 110.0).sim
    assert sim.set_pump("on", pump_id="pump-2-3")["status"] == "on"
    assert sim.set_pump("on", incident_id="inc-0001")["status"] == "duplicate"
    assert sim.set_pump("off", pump_id="pump-2-3") == {"status": "off", "pump_id": "pump-2-3", "state": "off", "capacity_m3s": 0.0}
    assert sim.set_pump("on", pump_id="nope")["reason"] == "unknown_pump"
    assert sim.set_pump("on", incident_id="inc-9999")["reason"] == "unknown_incident"
    assert sim.set_pump("sideways", pump_id="pump-2-3")["reason"] == "unknown_state"


def test_without_rain_the_dip_stays_dry_in_the_other_scenarios():
    sim = scenarios.run("city", 60.0).sim
    assert sim.flood_zones[0].depth_m == 0.0 and not sim.flooded_edges
    assert not [e for e in sim.timeline if e["kind"] in ("rain_started", "street_flooded")]
