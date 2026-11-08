"""The movement rules on full simulation runs (see tools/check_rules.py)."""
import pytest

from twin.engine.street_profile import CROSSWALK_WIDTH_M, SIDEWALK_WIDTH_M, kerb_offset
from twin.engine.traffic_lights import build_traffic_lights
from twin.engine.walk_network import build_walk_network
from tools import check_rules
from tools.check_rules import CONFIGS, SEEDS, rule_violations, run_forced_collision, run_movement_checks
from twin.world.map import STREETS, build_two_blocks_graph


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("scenario", [kw for _, kw in CONFIGS], ids=["spike-5-cars-5-peds", "dense-15-cars-25-peds"])
def test_no_rule_violations(scenario, seed):
    result = run_movement_checks(120.0, seed=seed, **scenario)
    assert result["walking_ticks"] > 0
    assert rule_violations(result) == {}


def test_car_hitting_pedestrian_is_flagged_and_cleared():
    outcome = run_forced_collision()
    assert outcome.startswith("PASS"), outcome


def test_check_constants_match_the_engine_geometry():
    """check_rules spells the cross-section out by hand (so it does not trust the engine);
    this keeps that spec and the engine's street profile from drifting apart."""
    road = build_two_blocks_graph()
    walk = build_walk_network(road, set(build_traffic_lights(road)))
    for a, b in STREETS:
        assert kerb_offset(road, a, b) == check_rules.KERB_M
    assert SIDEWALK_WIDTH_M == check_rules.SIDEWALK_M
    assert CROSSWALK_WIDTH_M == check_rules.CROSSWALK_W
    assert {cw.along_m for cw in walk.crosswalks.values()} == {check_rules.CROSSWALK_ALONG_M}


def test_rule_geometry_flags_obvious_violations():
    assert check_rules.on_asphalt_outside_crosswalk(40.0, -2.5)        # middle of a lane
    assert not check_rules.on_asphalt_outside_crosswalk(70.0, -2.5)    # on crosswalk cw_2_1
    assert check_rules.past_building_line(40.0, 40.0)                  # inside block A
    assert not check_rules.past_building_line(40.0, -10.0)             # on the sidewalk
    assert check_rules.path_crosses_road(40.0, -10.0, 40.0, 10.0)      # straight across the street
    assert not check_rules.path_crosses_road(70.0, -10.0, 70.0, 10.0)  # over the crosswalk
