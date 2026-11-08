"""The solvers are asked by the teams they serve: each answer is in the brief, computed in code, and the scripted team reads it."""

from types import SimpleNamespace

from brain.config import ModelsConfig, Policy
from brain.departments.facts import engine_facts, sentences
from brain.scenario import inproc_partners, load_scenario, run_scenario
from tests.test_scenarios import play

DESKS = ModelsConfig.model_validate({"embeddings": {"provider": "hashing"}, "team": {"departments": "on"}})


async def assessed(scenario_id, department):
    result = await run_scenario(load_scenario(scenario_id), inproc_partners(), models=DESKS, speed=0, timeout_s=30)
    return [e.data for e in result.sink.of("brain.desk.assessed") if e.data["department"] == department]


async def test_the_traffic_control_desk_reads_the_corridors_that_hold_signals():
    act = SimpleNamespace(corridors=[{"incident_id": "inc-1", "path": ["zone-01", "zone-04", "zone-03"], "signals": ["signal-04"]}], shedder=None)
    deps = SimpleNamespace(policy=Policy(), actuation=act, forecasts=None)

    facts = await engine_facts("MOBILITY", SimpleNamespace(incident_id="inc-2", type="jam", zone_id="zone-02"), None, deps)

    assert facts["corridors"][0]["signals"] == ["signal-04"] and "1 emergency corridor hold" in sentences(facts)[0]


async def test_a_solver_that_is_off_leaves_its_key_out_of_the_brief():
    deps = SimpleNamespace(policy=Policy.model_validate({"optimiser": {"dispatch": "off"}}), actuation=SimpleNamespace(corridors=[], shedder=None), forecasts=None)

    assert await engine_facts("FIRE", SimpleNamespace(incident_id="inc-1", type="fire", zone_id="zone-06"), None, deps) == {}


async def test_a_perimeter_that_holds_more_units_than_a_solver_says_is_sent_back_once_and_then_stands():
    policy = Policy.model_validate({"optimiser": {"perimeter_slack": -3}})  # no plan is tight enough: the critic fires on the first plan

    result = await play(load_scenario("t14"), policy=policy)

    rejected = result.sink.of("brain.plan.rejected")
    assert len(rejected) == 1 and "a solver says" in " ".join(rejected[0].data["problems"])
    assert result.sink.of("brain.plan.verified")
