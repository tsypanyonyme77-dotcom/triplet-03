"""End-to-end: the real Brain against the mock Twin (MCP) and mock Guardian (REST), in-process."""

import pytest

from brain.config import ModelsConfig, Policy
from brain.scenario import evaluate, inproc_partners, load_scenario, run_scenario
from brain.timeline import MemorySink, verify_chain

MODELS = ModelsConfig.model_validate({"embeddings": {"provider": "hashing"}})


async def play(scenario, partners_context=None, **kwargs):
    kwargs.setdefault("models", MODELS)
    return await run_scenario(scenario, partners_context or inproc_partners(), speed=0, timeout_s=20, **kwargs)


def failed(result):
    return [f"{c.name}: {c.detail}" for c in result.checks if not c.passed]


@pytest.mark.parametrize("scenario_id", ["d1", "d2", "d3", "d4"])
async def test_test_book_scenario(scenario_id, tmp_path):
    result = await play(load_scenario(scenario_id), log_dir=tmp_path)

    assert result.passed, failed(result)
    assert result.log_path.name.startswith(f"{scenario_id}-")
    assert verify_chain(result.log_path)[0]


async def test_pursuit_call_follows_the_contract():
    result = await play(load_scenario("d3"))

    call = result.actuator_calls[0]["call"]
    assert call["action"] == "dispatch_unit"
    assert call["requesting_layer"] == "city_brain"
    assert call["actuator_id"] == "police-dispatch-05"  # nearest station to Downtown
    assert call["trust_ref"].startswith("verdict-")
    assert call["provenance"]["signed_by"] == "city_brain"
    assert "cit-88213" in call["justification"] and "POL-001" in call["justification"]

    decision = result.sink.of("brain.decision.made")[0].data
    assert call["trust_ref"] in decision["citations"]
    assert "cam-07-02#1" in decision["citations"]


async def test_every_event_traces_back_to_a_reading():
    result = await play(load_scenario("d3"))

    request = result.sink.of("brain.action.requested")[0]
    assert request.traceid == "cit-feed-07:4"  # the sighting that tipped the score
    order = result.sink.types()
    assert order.index("brain.verdict.received") < order.index("brain.decision.made") < order.index("brain.action.requested")


async def test_guardian_down_means_no_dispatch():
    scenario = load_scenario("d3")
    scenario["guardian"] = {"down": True}
    scenario["expect"] = {
        "dispatched": [],
        "forbidden_events": ["brain.action.requested", "brain.deliberation.started"],
        "event_counts": {"brain.guardian.unavailable": 1, "brain.action.blocked": 1},
    }

    result = await play(scenario)

    assert result.passed, failed(result)


async def test_the_reflex_tier_works_alone_when_the_team_is_switched_off():
    models = ModelsConfig.model_validate({"team": {"enabled": False}, "embeddings": {"provider": "hashing"}})

    result = await play(load_scenario("d3"), models=models)

    assert [c["call"]["params"]["mode"] for c in result.actuator_calls] == ["pursuit"]
    assert "brain.deliberation.started" not in result.sink.types()


async def test_a_twin_without_public_alerts_gets_a_plan_without_them():
    result = await play(load_scenario("d3"), inproc_partners(frozenset({"broadcast_alert"})))

    assert [c["call"]["action"] for c in result.actuator_calls] == ["dispatch_unit"] * 3 + ["recall_unit"] * 2
    assert result.sink.of("brain.plan.verified")[0].data["alert_zones"] == []
    assert "POL-PB-005" not in result.sink.of("brain.plan.verified")[0].data["playbook"]


async def test_when_the_twin_runs_out_of_units_the_brain_records_the_refusal():
    scenario = load_scenario("d3")
    for facility in scenario["topology"]["facilities"]:
        facility["units"] = 1  # two police units in the whole city

    result = await play(scenario)

    # One pursues; the single remaining unit must stay in reserve, so no perimeter is committed.
    assert [c["call"]["params"]["mode"] for c in result.actuator_calls if c["call"]["action"] == "dispatch_unit"] == ["pursuit"]
    assert result.sink.of("brain.plan.verified")[0].data["option"] == "pursuit-only"


def ambiguous_case():
    """b2 without the sighting at the scene, and with the Station feed marked suspicious."""
    scenario = load_scenario("d3")
    scenario["events"] = [e for e in scenario["events"] if e["at_ms"] != 1500]
    scenario["guardian"] = {"default": "trusted", "overrides": {"cit-feed-08": "suspicious"}}
    policy = Policy()
    policy.scoring.poi_threshold = 0.4
    return scenario, policy


async def test_the_scripted_team_only_watches_an_ambiguous_case():
    scenario, policy = ambiguous_case()

    result = await play(scenario, policy=policy)

    assert result.actuator_calls == []
    assert result.sink.of("brain.suspect.assessed")[0].data["level"] == "poi"
    review = result.sink.of("brain.case.reviewed")[0].data
    assert (review["recommendation"], review["mode"]) == ("watch", "scripted")


def test_evaluate_checks_actuated_calls():
    expect = {"actuated": [{"action": "set_signal_phase", "params": {"phase": "green"}}]}
    sent = {"call": {"action": "set_signal_phase", "params": {"phase": "green", "duration_s": 120}, "trust_ref": "verdict-000001"},
            "result": {"status": "set"}}
    refused = {**sent, "result": {"status": "rejected", "reason": "no"}}

    assert all(c.passed for c in evaluate(expect, MemorySink(), [sent]))
    assert not all(c.passed for c in evaluate(expect, MemorySink(), []))
    assert not all(c.passed for c in evaluate(expect, MemorySink(), [refused]))


