"""When units run out, a named suspect's pursuit may take a perimeter unit from an incident that still has its own pursuit out."""

from brain.scenario import load_scenario
from tests.plain import plain  # noqa: E402
from tests.test_scenarios import failed, play

PREEMPT = plain(tactics={"preempt_perimeter": True})


def pursuits(result):
    return sorted(c["call"]["params"]["target_id"] for c in result.actuator_calls if c["call"]["params"].get("mode") == "pursuit")


def blocks(result):
    return [e.data["check"] for e in result.sink.of("brain.action.blocked")]


async def test_a_pursuit_is_not_helped_by_taking_a_unit_from_the_only_incident_that_has_one():
    scenario = load_scenario("t14")  # one robbery: nothing to take, nothing to fix

    result = await play(scenario, policy=PREEMPT)

    assert result.passed, failed(result)
    assert not [e for e in result.sink.of("brain.units.released") if "reempt" in e.data["cause"]]


