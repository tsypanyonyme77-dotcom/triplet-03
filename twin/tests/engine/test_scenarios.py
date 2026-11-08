"""Scripted scenarios: the staged event happens as designed, everyone else keeps the rules."""
import pytest

from tools.check_rules import rule_violations, run_movement_checks
from twin.world import scenarios
from twin.world.scenarios import CityParams

FULL = CityParams(scenarios.MAX_CARS, scenarios.MAX_PEDESTRIANS, 0.0, 0.0)


def _rule_violations(result: dict) -> dict:
    return rule_violations(result)


def test_ped_hit_car_hits_the_distracted_pedestrian_on_the_crosswalk():
    sc = scenarios.build("ped-hit")
    result = run_movement_checks(90.0, scenario=sc)
    assert _rule_violations(result) == {}

    assert len(sc.sim.accidents) == 1, sc.sim.accidents
    a = sc.sim.accidents[0]
    assert a["kind"] == "car_pedestrian"
    assert (a["car_id"], a["pedestrian_id"]) == (sc.actors["car"], sc.actors["pedestrian"])
    assert a["pedestrian_on_crosswalk"]
    assert 68.5 <= a["x"] <= 71.5 and -5.0 <= a["y"] <= 0.0  # crosswalk cw_2_1, eastbound lane
    assert a["car_speed_ms"] > 8.0                            # hit at speed, not a creep
    assert a["cleared_t"] is None                             # nothing is dispatched: it waits for a call
    assert sc.sim.cars[sc.actors["car"]].status == "crashed" and sc.sim.pedestrians[sc.actors["pedestrian"]].status == "injured"


def test_ped_hit_adapts_to_other_background_traffic():
    for seed in (2, 13):
        sc = scenarios.run("ped-hit", 90.0, seed=seed)
        assert [(a["car_id"], a["pedestrian_id"]) for a in sc.sim.accidents] == [
            (sc.actors["car"], sc.actors["pedestrian"])
        ], seed


def test_clean_city_keeps_the_rules_and_has_no_accident():
    result = run_movement_checks(120.0, scenario=scenarios.build("city", params=CityParams().clean()))
    assert _rule_violations(result) == {}
    assert result["accidents"] == 0


def test_car_crash_red_light_runner_hits_the_crossing_car():
    sc = scenarios.build("car-crash")
    result = run_movement_checks(90.0, scenario=sc)
    assert _rule_violations(result) == {}

    assert len(sc.sim.accidents) == 1, sc.sim.accidents
    a = sc.sim.accidents[0]
    assert (a["kind"], a["cause"]) == ("car_car", "ran_red_light")
    assert (a["car_id"], a["other_car_id"]) == (sc.actors["striking"], sc.actors["struck"])
    assert abs(a["x"] - 77.5) < 3.0 and 0.0 < a["y"] < 5.0   # runner's front in the westbound lane at node 2
    assert a["car_speed_ms"] > 8.0 and a["other_car_speed_ms"] > 8.0
    assert a["cleared_t"] is None
    assert sc.sim.cars[sc.actors["striking"]].status == sc.sim.cars[sc.actors["struck"]].status == "crashed"


def test_car_crash_adapts_to_other_background_traffic():
    for seed in (2, 8):  # 2 needs a second attempt: a car passes the runner's start point the first time
        sc = scenarios.run("car-crash", 100.0, seed=seed)
        assert [(a["kind"], a["car_id"], a["other_car_id"]) for a in sc.sim.accidents] == [
            ("car_car", sc.actors["striking"], sc.actors["struck"])
        ], seed


def test_a_full_city_keeps_moving():
    sc = scenarios.build("city", params=FULL)
    assert (len(sc.sim.cars), len(sc.sim.pedestrians)) == (scenarios.MAX_CARS, scenarios.MAX_PEDESTRIANS)
    drove, walked = set(), set()
    for _ in range(1200):  # 120 s
        sc.step()
        drove |= {c.id for c in sc.sim.cars.values() if c.status == "driving"}
        walked |= {p.id for p in sc.sim.pedestrians.values() if p.status == "walking"}
    assert len(drove) >= 30, len(drove)  # cars still find free spots to drive to
    assert len(walked) >= 95, len(walked)
    assert sc.sim.accidents == []


def test_a_full_city_keeps_the_rules():
    result = run_movement_checks(180.0, scenario=scenarios.build("city", params=FULL))
    assert _rule_violations(result) == {}


def _accident_kinds(params: CityParams) -> list[set[str]]:
    return [{a["kind"] for a in scenarios.run("city", 180.0, seed, params).sim.accidents} for seed in (1, 2, 3)]


def test_each_risk_causes_only_its_own_kind_of_accident():
    """Seeds are fixed, so this is deterministic."""
    crashes = _accident_kinds(CityParams(car_crash_risk=0.5, ped_hit_risk=0.0))
    hits = _accident_kinds(CityParams(car_crash_risk=0.0, ped_hit_risk=0.5))
    assert any(crashes) and all(kinds <= {"car_car"} for kinds in crashes), crashes
    assert any(hits) and all("car_car" not in kinds for kinds in hits), hits


def test_risk_decides_who_is_reckless_and_zero_means_nobody():
    risky = scenarios.build("city", seed=1, params=CityParams(car_crash_risk=0.5, ped_hit_risk=0.5)).sim
    assert any(not c.obeys_signals for c in risky.cars.values())
    assert any(not c.yield_to_pedestrians for c in risky.cars.values())
    assert any(p.distracted for p in risky.pedestrians.values())
    clean = scenarios.build("city", seed=1, params=CityParams().clean()).sim
    assert all(c.obeys_signals and c.yield_to_pedestrians and c.respects_junctions for c in clean.cars.values())
    assert not any(p.distracted for p in clean.pedestrians.values())


@pytest.mark.parametrize("params", [{"cars": 48}, {"pedestrians": 101}, {"cars": -1},
                                    {"car_crash_risk": 1.5}, {"ped_hit_risk": -0.1}])
def test_city_params_out_of_range_are_refused_clearly(params):
    with pytest.raises(ValueError, match=next(iter(params))):
        CityParams(**params)
