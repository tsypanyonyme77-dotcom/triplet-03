"""No teleports, no pop-in, no sliding, for every vehicle and pedestrian in every scenario
(tools/continuity.py, on the recorded frames).

Marked xfail(strict=True) until the engine is fixed: the current engine still stops
cars dead, slides them into parking spots, spawns staged cars and ambulances mid-street
and removes wrecks. strict=True makes a scenario that becomes clean fail as XPASS,
so the marker is removed then and the check guards it from that point on.
"""
import pytest

from tools.continuity import SCENARIO_SECONDS, check, record_frames

KNOWN_FAILING = pytest.mark.xfail(strict=True, reason="engine not continuous yet (feat/realistic-physics, step 1)")


@pytest.mark.parametrize("name", [pytest.param(n, marks=KNOWN_FAILING) for n in SCENARIO_SECONDS])
def test_every_entity_moves_continuously(name):
    frames, entries = record_frames(name, SCENARIO_SECONDS[name])
    result = check(frames, entries)
    assert sum(result["violations"].values()) == 0, result


def _car(t, x, speed, heading=0.0, y=0.0):
    return {"t": t, "cars": [["c", x, y, heading, speed, "driving"]], "pedestrians": []}


def _violations(*frames):
    return check(list(frames), entries=[])["violations"]


@pytest.mark.parametrize("name", list(SCENARIO_SECONDS))
def test_driving_cars_move_continuously(name):
    """Fixed by the bicycle model (step 2): a car on the road never jumps, slides, crabs,
    over-turns or over-brakes. Parking, crashes, ambulances and pedestrians are still open."""
    frames, entries = record_frames(name, SCENARIO_SECONDS[name])
    driving = {k: n for k, n in check(frames, entries)["breakdown"].items() if k.endswith("car driving -> driving")}
    assert driving == {}


def test_checker_flags_a_teleport():
    assert _violations(_car(0.1, 0.0, 10.0), _car(0.2, 8.0, 10.0))["teleport"] == 1


def test_checker_flags_moving_while_reporting_standstill():
    v = _violations(_car(0.1, 0.0, 0.0), _car(0.2, 0.5, 0.0))
    assert v["slide"] == 1


def test_checker_flags_sideways_motion_and_turning_on_the_spot():
    assert _violations(_car(0.1, 0.0, 2.0), _car(0.2, 0.0, 2.0, y=0.2))["crab"] == 1
    assert _violations(_car(0.1, 0.0, 0.0), _car(0.2, 0.0, 0.0, heading=0.3))["yaw"] == 1


def test_checker_flags_stopping_dead():
    assert _violations(_car(0.1, 0.0, 10.0), _car(0.2, 1.0, 0.0))["accel"] == 1


def test_checker_flags_vanishing_mid_map_but_not_at_a_map_exit():
    frames = [_car(0.1, 0.0, 10.0), {"t": 0.2, "cars": [], "pedestrians": []}]
    assert check(frames, entries=[])["violations"]["pop"] == 1
    assert check(frames, entries=[(5.0, 0.0)])["violations"]["pop"] == 0


def test_checker_accepts_smooth_driving():
    frames = [
        {"t": round(0.1 * i, 1), "cars": [["c", 1.0 * i, 0.0, 0.0, 10.0, "driving"]], "pedestrians": []}
        for i in range(1, 30)
    ]
    assert sum(check(frames, entries=[])["violations"].values()) == 0
