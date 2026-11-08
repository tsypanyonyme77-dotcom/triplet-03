"""The staged building-fire scenario: a building catches fire and the city reacts to it."""
import pytest

from twin.world import scenarios
from twin.world.scenario import DT


@pytest.mark.parametrize("seed", [7, 3, 11])
def test_the_building_catches_fire_after_the_warm_up_whatever_the_background(seed):
    sc = scenarios.build("building-fire", seed=seed)
    sim = sc.sim
    for _ in range(round((scenarios.FIRE_START_S - 1) / DT)):
        sc.step()
    assert sim.fire.fires == []
    for _ in range(round(60 / DT)):
        sc.step()
    assert [(f["building_id"], f["cause"]) for f in sim.fire.fires[:1]] == [(sc.actors["building"], "scenario")]
    assert sim.fire.fires[0]["incident_id"] == "inc-0001"          # the smoke sensor opened it
    assert sim.accidents == [] and sim.hazard_edges                  # only a fire, and the city keeps away from it


def test_the_scenario_is_listed_with_the_others_and_burns_until_someone_answers():
    assert "building-fire" in scenarios.SCENARIOS
    sc = scenarios.run("building-fire", 200.0)
    assert sc.sim.fire.open()                       # nothing dispatches a truck on its own
    assert len(sc.sim.fire.fires) > 1               # ... so it spreads to the buildings next to it
    assert all(f["cause"] in ("scenario", "spread") for f in sc.sim.fire.fires)
