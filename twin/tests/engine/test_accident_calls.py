"""Accidents wait for a call: nothing is dispatched on its own (the Twin's other layers decide),
and clear_accident / dispatch_ambulance are the calls that answer them."""
from twin.world import scenarios
from twin.world.scenarios import CityParams
from twin.world.scenario import DT


def _staged_hit(seconds: float = 90.0):
    """ped-hit: a careless driver hits a pedestrian on a crosswalk."""
    sc = scenarios.run("ped-hit", seconds)
    assert len(sc.sim.accidents) == 1
    return sc


def test_an_accident_dispatches_nothing_and_stays_until_called():
    sc = _staged_hit()
    sim = sc.sim
    accident = sim.accidents[0]
    for _ in range(int(120 / DT)):  # two more minutes: no ambulance comes
        sc.step()
    assert accident["cleared_t"] is None
    assert all(a.status == "idle" for a in sim.ambulances.values())
    assert sc.actors["car"] in sim.cars and sim.cars[sc.actors["car"]].status == "crashed"
    assert sim.pedestrians[sc.actors["pedestrian"]].status == "injured"
    assert [a["id"] for a in sim.state()["accidents"]] == [accident["id"]]  # still reported


def test_clear_accident_removes_the_wreck_and_the_injured_pedestrian():
    sc = _staged_hit()
    sim = sc.sim
    accident = sim.accidents[0]
    assert sim.clear_accident(accident["id"])
    assert accident["cleared_t"] is not None
    assert sc.actors["car"] not in sim.cars and sc.actors["pedestrian"] not in sim.pedestrians
    assert sim.state()["accidents"] == []
    assert not sim.clear_accident(accident["id"])  # already cleared
    assert not sim.clear_accident("acc99")         # unknown


def test_clear_accident_removes_both_cars_of_a_car_crash():
    sc = scenarios.run("car-crash", 90.0)
    sim = sc.sim
    assert sim.clear_accident(sim.accidents[0]["id"])
    assert sc.actors["striking"] not in sim.cars and sc.actors["struck"] not in sim.cars


def test_dispatch_ambulance_is_still_there_as_a_call():
    """The old automatic response, now only on request: an ambulance drives to the scene,
    cleans up, and the accident is cleared."""
    sc = _staged_hit()
    sim = sc.sim
    accident = sim.accidents[0]
    assert sim.dispatch_ambulance(accident["id"])
    for _ in range(int(300 / DT)):
        sc.step()
        if accident["cleared_t"] is not None:
            break
    assert accident["cleared_t"] is not None
    assert sc.actors["car"] not in sim.cars and sc.actors["pedestrian"] not in sim.pedestrians
    assert not sim.dispatch_ambulance(accident["id"])  # nothing left to answer


def test_dispatch_ambulance_rejects_unknown_accidents():
    sim = scenarios.build("city", params=CityParams().clean()).sim
    assert not sim.dispatch_ambulance("acc1")
