"""The four demo scenarios: each passes, each proves one claim, and each fails when the behaviour it proves is taken away."""

import copy
import json

import pytest

from brain.config import ModelsConfig
from brain.scenario import inproc_partners, load_scenario, run_scenario

MODELS = ModelsConfig.model_validate({"embeddings": {"provider": "hashing"}})
IDS = ["d1", "d2", "d3", "d4"]


async def play(scenario):
    return await run_scenario(scenario, inproc_partners(), models=MODELS, speed=0, timeout_s=30)


@pytest.mark.parametrize("scenario_id", IDS)
async def test_each_demo_scenario_passes_and_states_its_claim(scenario_id):
    scenario = load_scenario(scenario_id)

    assert scenario["claim"].startswith("Proves: ") and scenario["how_to_verify"]
    result = await play(scenario)
    assert result.passed, [c for c in result.checks if not c.passed]


async def test_a_fake_flood_acts_when_the_guardian_trusts_the_lying_sensor():
    scenario = load_scenario("d2")
    scenario["guardian"] = {"default": "trusted", "overrides": {}}

    assert not (await play(scenario)).passed  # the warning goes out, so "the gate refused it" no longer holds


async def test_a_fake_flood_sends_nothing_to_the_city():
    result = await play(load_scenario("d2"))

    assert result.actuator_calls == []


async def test_a_pursuit_is_not_sent_when_the_robbery_report_is_untrusted():
    scenario = load_scenario("d3")
    scenario["guardian"] = {"default": "trusted", "overrides": {"cam-07-02": "untrusted"}}

    assert not (await play(scenario)).passed


async def test_the_layer_down_scenario_needs_the_guardian_to_go_quiet():
    scenario = load_scenario("d4")
    scenario.pop("faults")

    assert not (await play(scenario)).passed  # no brain.guardian.unavailable without the fault


async def test_the_layer_down_scenario_sends_the_alert_but_never_the_valve():
    result = await play(load_scenario("d4"))

    actions = {c["call"]["action"] for c in result.actuator_calls}
    assert "broadcast_alert" in actions and "set_valve_state" not in actions
    assert result.sink.types().count("brain.guardian.unavailable") == 1


async def test_a_calm_day_opens_no_incident():
    result = await play(load_scenario("d1"))

    assert result.sink.types().count("brain.incident.opened") == 0 and result.actuator_calls == []


async def test_a_demo_scenario_decides_the_same_twice():
    def decisions(result):
        return [json.dumps({"action": e.data["action"], "params": e.data["params"]}, sort_keys=True) for e in result.sink.of("brain.decision.made")]

    first, second = await play(copy.deepcopy(load_scenario("d4"))), await play(copy.deepcopy(load_scenario("d4")))
    assert decisions(first) == decisions(second) and decisions(first)
