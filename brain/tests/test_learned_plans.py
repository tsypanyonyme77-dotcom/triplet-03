"""A plan the team made the same way before, compiled into a reflex: same decisions, no team run."""

import json
import textwrap

import pytest

from brain import config
from brain.config import BrainConfig, PartnersConfig, Policy
from brain.scenario import load_scenario
from tests.test_scenarios import failed, play

B2_PLAN = textwrap.dedent("""
    rules:
      - id: LRN-1
        name: learned.plan.zone-07.zone-08
        scope: plan
        description: Test copy of the team's plan for a robbery in zone-07 with the suspect heading to zone-08.
        when:
          incident.type: crime
          incident.zone_id: zone-07
          assessment.level: suspect
          assessment.last_zone_id: zone-07
          assessment.heading_zone_id: zone-08
        do:
          - action: dispatch_unit
            params: {unit_type: police, zone_id: zone-04, incident_id: $incident.incident_id, mode: contain, target_id: $assessment.entity_id}
          - action: dispatch_unit
            params: {unit_type: police, zone_id: zone-08, incident_id: $incident.incident_id, mode: contain, target_id: $assessment.entity_id}
          - action: broadcast_alert
            params: {message: "Police activity in Downtown. Please avoid the area.", channel: app, zone_id: zone-07}
        learned: {sources: [ep-test-1, ep-test-2], support: 2}
""")


def learned(folder, text=B2_PLAN) -> PartnersConfig:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "rules.yaml").write_text(text)
    return PartnersConfig(brain=BrainConfig(learned_dir=str(folder)))


def decisions(result):
    return sorted(({"action": e.data["action"], "actuator_id": e.data["actuator_id"], "params": e.data["params"]}
                   for e in result.sink.of("brain.decision.made")), key=lambda d: json.dumps(d, sort_keys=True))


async def test_a_learned_plan_gives_the_same_decisions_with_no_team_run(tmp_path):
    taught = await play(load_scenario("t14"), partners=learned(tmp_path))
    team = await play(load_scenario("t14"))

    # The scenario's own order checks name the team's events, which a learned plan rightly replaces; the decisions are what must not move.
    assert decisions(taught) == decisions(team)
    assert "brain.deliberation.started" not in taught.sink.types() and "brain.deliberation.started" in team.sink.types()
    (event,) = taught.sink.of("brain.plan.compiled")
    assert event.data["rule_id"] == "LRN-1" and len(event.data["actions"]) == 3
    assert {e.data["tier"] for e in taught.sink.of("brain.decision.made")} == {"reflex"}


async def test_a_learned_plan_that_cannot_be_fully_proposed_falls_back_to_the_team(tmp_path):
    scenario = load_scenario("t14")
    # One station with two units: the pursuit and one perimeter unit use them both, so the third part of the plan has no unit.
    scenario["topology"]["facilities"] = [f for f in scenario["topology"]["facilities"] if f["id"] != "ps-09"]

    taught = await play(scenario, partners=learned(tmp_path))
    team = await play(json.loads(json.dumps(scenario)))

    assert taught.sink.of("brain.plan.compiled") == []
    assert "brain.deliberation.started" in taught.sink.types()
    assert decisions(taught) == decisions(team)  # exactly what the team alone decides: no half of a learned plan went out


@pytest.mark.parametrize("scenario_id", ["t12", "t13"])
async def test_a_learned_rule_that_does_not_match_the_signature_changes_nothing(tmp_path, scenario_id):
    saved = json.loads((config.home() / "docs/baseline/2026-11-07-demo-frozen.json").read_text())
    folder = tmp_path / scenario_id
    with_rule = await play(load_scenario(scenario_id), partners=learned(folder))

    assert with_rule.passed, failed(with_rule)
    assert with_rule.sink.of("brain.plan.compiled") == []
    assert decisions(with_rule) == saved[scenario_id]["decisions"]


async def test_a_plan_rule_never_fires_for_a_person_of_interest(tmp_path):
    only_poi = B2_PLAN.replace("assessment.level: suspect", "assessment.level: poi")

    result = await play(load_scenario("t14"), partners=learned(tmp_path, only_poi))

    assert result.sink.of("brain.plan.compiled") == []


async def test_learning_can_be_switched_off(tmp_path):
    result = await play(load_scenario("t14"), partners=learned(tmp_path), policy=Policy.model_validate({"learning": {"use_learned": False}}))

    assert result.sink.of("brain.plan.compiled") == [] and "brain.deliberation.started" in result.sink.types()


async def test_a_scenario_still_passes_when_a_learned_plan_replaced_the_team_run(tmp_path):
    result = await play(load_scenario("t14"), partners=learned(tmp_path))

    assert result.passed, failed(result)
    skipped = [c for c in result.checks if "learned plan" in c.detail]
    assert skipped and all("deliberation.started" in c.name for c in skipped)
    assert not any("learned plan" in c.detail for c in (await play(load_scenario("t14"))).checks)
