"""The workspace inside the running Brain: behind a flag, and never changing what the Brain decides."""


from brain.config import Policy
from brain.scenario import load_scenario
from tests.test_scenarios import failed, play

ALL = [f"b{n}" for n in range(1, 15)]


async def test_an_incident_that_is_not_lit_gets_its_reflex_response_but_no_team():
    policy = Policy.model_validate({"workspace": {"slots": 0}})

    result = await play(load_scenario("t14"), policy=policy)

    modes = [c["call"]["params"].get("mode") for c in result.actuator_calls if c["call"]["action"] == "dispatch_unit"]
    assert modes == ["pursuit"]
    assert "brain.deliberation.started" not in result.sink.types()
    assert result.sink.of("brain.workspace.deferred")


async def test_the_started_event_reports_the_workspace_settings():
    result = await play(load_scenario("t12"))

    assert result.sink.of("brain.started")[0].data["workspace"] == {"enabled": True, "slots": 2}


async def test_a_crime_that_the_team_works_holds_a_slot_until_it_closes():
    result = await play(load_scenario("t14"))

    assert result.passed, failed(result)
    order = result.sink.types()
    assert order.index("brain.workspace.ignited") < order.index("brain.deliberation.started")
    assert [e.data["reason"] for e in result.sink.of("brain.workspace.released")] == ["closed"]


async def test_an_incident_that_stays_open_with_no_new_evidence_says_a_person_may_be_needed_once():
    stalls = await play(load_scenario("t14"), policy=Policy.model_validate({"triage": {"stall_s": 1}}))
    plain = await play(load_scenario("t14"))

    needed = [e for e in stalls.sink.of("brain.human.needed") if e.data["why"] == "stalled"]
    assert needed and len({e.subject for e in needed}) == len(needed)
    assert not plain.sink.of("brain.human.needed")
