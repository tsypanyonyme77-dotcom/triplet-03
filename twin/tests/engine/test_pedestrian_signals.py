"""The pedestrian phase: every car light red while people walk, so turning cars do not wait for them."""
import pytest

from tools.check_rules import run_movement_checks
from twin.engine import traffic_lights as tl
from twin.engine.crossing_rules import may_cross
from twin.world import scenarios
from twin.world.scenarios import CityParams


def _light_at(t: float):
    light = tl.TrafficLight(node_id=1, approach_phase={10: 0, 20: 1})
    tl.tick_lights({1: light}, t)
    return light


def test_the_cycle_runs_both_car_phases_then_walk_then_flash():
    phase, g = tl.phase_s(), tl.GREEN_S
    states = [(_light_at(t).phase_a_state, _light_at(t).phase_b_state, _light_at(t).walk_state)
              for t in (0, g, phase, phase + g, 2 * phase, 2 * phase + tl.WALK_S)]
    assert states == [("green", "red", tl.DONT_WALK), ("yellow", "red", tl.DONT_WALK), ("red", "green", tl.DONT_WALK),
                      ("red", "yellow", tl.DONT_WALK), ("red", "red", tl.WALK), ("red", "red", tl.WALK_FLASH)]


def test_every_car_light_is_red_whenever_people_may_walk():
    for tenth in range(int(tl.cycle_s() * 10)):
        light = _light_at(tenth / 10)
        if light.walk_state != tl.DONT_WALK:
            assert (light.phase_a_state, light.phase_b_state) == ("red", "red"), tenth


@pytest.mark.parametrize("t,from_node,left", [
    (0.0, 10, tl.GREEN_S),                                   # phase A's green
    (tl.GREEN_S, 10, tl.YELLOW_S),                           # phase A's yellow
    (tl.phase_s(), 10, tl.cycle_s() - tl.phase_s()),         # phase A's red, to the end of the cycle
    (tl.phase_s(), 20, tl.GREEN_S),                          # phase B's green
    (0.0, 20, tl.phase_s()),                                 # phase B's red, a phase A away
    (2 * tl.phase_s(), 20, tl.cycle_s() - tl.phase_s()),     # phase B's red, through the walk
])
def test_seconds_until_change_knows_the_pedestrian_phase(t, from_node, left):
    assert _light_at(t).seconds_until_change(from_node) == pytest.approx(left)


def test_the_flash_lets_someone_stepping_off_last_clear_the_road():
    asphalt_m = 16.0
    assert tl.WALK_FLASH_S >= asphalt_m / 1.4


@pytest.mark.parametrize("state,allowed", [(tl.WALK, True), (tl.WALK_FLASH, False), (tl.DONT_WALK, False)])
def test_only_walk_lets_a_pedestrian_step_off(state, allowed):
    assert may_cross(state, []) is allowed


def test_walk_still_waits_for_a_car_too_close():
    assert may_cross(tl.WALK, [(5.0, 8.0)]) is False


def test_an_unsignalised_crosswalk_goes_by_the_gap():
    assert may_cross(None, []) is True


def test_nobody_following_the_signal_steps_off_without_walk_and_cars_do_not_wait_for_them():
    sc = scenarios.build("city", seed=2, params=CityParams(20, 40, 0.0, 0.0))
    result = run_movement_checks(180.0, scenario=sc)
    assert result["R1d_ped_entered_crosswalk_without_walk"] == 0
    assert result["accidents"] == 0


def test_distracted_pedestrians_ignore_the_signal():
    sim = scenarios.build("city", seed=1, params=CityParams(20, 40, 0.0, 1.0)).sim
    assert all(p.distracted for p in sim.pedestrians.values() if p.force.desired_speed < 2.0)
    entered_without_walk = 0
    sc = scenarios.build("city", seed=1, params=CityParams(10, 40, 0.0, 1.0))
    on_road = {}
    for _ in range(1200):
        sc.step()
        for p in sc.sim.pedestrians.values():
            cw = None
            if p.edge_index > 0 and p.status == "walking":
                cw = sc.sim.walk.crosswalk_between(p.route_nodes[p.edge_index - 1], p.route_nodes[p.edge_index])
            if cw and on_road.get(p.id) != cw.id and sc.sim.traffic_lights[cw.node].walk_state == tl.DONT_WALK:
                entered_without_walk += 1
            on_road[p.id] = cw.id if cw else None
    assert entered_without_walk > 0
