"""An explanation is built from the timeline log (and, when there is one, the knowledge base): the same log always gives the same
explanation, every id in it resolves, and a held action is explained as fully as a taken one."""

import json

import pytest

from brain.config import ModelsConfig
from brain.explain import explain_decision, explain_held, explain_incident
from brain.scenario import inproc_partners, load_scenario, run_scenario
from brain.timeline import read_log

HASHING = ModelsConfig.model_validate({"embeddings": {"provider": "hashing"}})  # the real embedder is for the retrieval tests


async def run(scenario_id: str, **kwargs):
    result = await run_scenario(load_scenario(scenario_id), inproc_partners(), models=HASHING, speed=0, timeout_s=30, **kwargs)
    assert result.passed, [c.name for c in result.checks if not c.passed]
    return result


def no_pump(event: dict) -> bool:
    """The mock city has no drainage pump, so every flood also holds the pump call for resources; these tests explain the other refusals."""
    return not (event["type"] == "brain.action.blocked" and event["data"].get("would_have") == "set_pump_state")


async def events_of(scenario_id: str) -> list[dict]:
    return [e for e in (event.model_dump(mode="json") for event in (await run(scenario_id)).sink.events) if no_pump(e)]


@pytest.fixture
async def b2() -> list[dict]:
    return await events_of("t14")


@pytest.fixture
async def b3() -> list[dict]:
    return await events_of("t13")


@pytest.fixture
async def b11() -> list[dict]:
    return await events_of("t15")


def types(e) -> list[str]:
    return [step.event_type for step in e.steps]


async def test_a_decision_explanation_walks_reading_verdict_incident_decision_action_in_order(b2):
    e = explain_decision(b2, "dec-0001")

    assert e.subject == "decision" and e.outcome == "acted" and e.id == "dec-0001"
    order = ["brain.reading.received", "brain.verdict.received", "brain.incident.opened", "brain.workspace.ignited",
            "brain.decision.made", "brain.action.requested", "brain.action.result"]
    positions = [types(e).index(t) for t in order]
    assert positions == sorted(positions)
    assert [step.n for step in e.steps] == list(range(1, len(e.steps) + 1))
    assert [step.at_ms for step in e.steps] == sorted(step.at_ms for step in e.steps)
    regions = {step.event_type: step.region for step in e.steps}
    assert regions["brain.reading.received"] == "senses" and regions["brain.decision.made"] == "reflex" and regions["brain.action.result"] == "twin"
    assert {step.layer for step in e.steps} == {"twin", "guardian", "brain"}
    assert "POL-001" in {k.id for k in e.knowledge} and e.checks and all(check.passed for check in e.checks)


async def test_a_team_decision_names_the_option_it_took_and_the_ones_it_left(b2):
    team = next(row["data"]["decision_id"] for row in b2 if row["type"] == "brain.decision.made" and row["data"]["tier"] == "deliberate")

    e = explain_decision(b2, team)

    assert {"brain.case.reviewed", "brain.options.prepared", "brain.plan.verified"} <= set(types(e))
    chosen = [a for a in e.alternatives if a.chosen]
    assert [a.name for a in chosen] == ["tight-perimeter"] and len(e.alternatives) == 4
    assert {"POL-PB-002", "POL-PB-006"} <= {k.id for k in e.knowledge}
    assert all(k.title for k in e.knowledge if k.id.startswith("POL-PB"))


async def test_a_held_action_names_the_failed_check_and_what_would_change_it(b11):
    held = [row for row in b11 if row["type"] == "brain.action.blocked"]
    assert [row["data"]["check"] for row in held] == ["evidence"]

    thin = explain_held(b11, held[0]["id"])
    assert thin.subject == "held" and thin.outcome == "held"
    assert thin.headline.startswith("Held") and "2 independent" in thin.headline + thin.checks[-1].reason
    assert [c.check for c in thin.checks if c.passed] == ["schema", "capability", "allowlist", "incident", "trust_ref"]
    assert thin.checks[-1].check == "evidence" and not thin.checks[-1].passed
    assert any(c.would_flip and "second independent" in c.change for c in thin.counterfactuals)


async def test_a_spoofed_report_is_explained_as_a_refusal_to_trust(b3):
    held = next(row for row in b3 if row["type"] == "brain.action.blocked")

    e = explain_held(b3, held["id"])

    assert e.checks[-1].check == "trust_ref" and not e.checks[-1].passed
    assert "wl-01-02#1" in " ".join(ids for step in e.steps for ids in step.ids)
    assert any("untrusted" in step.fact for step in e.steps if step.event_type == "brain.verdict.received")


async def test_the_same_log_always_gives_the_same_explanation(b2):
    first = explain_decision(b2, "dec-0003").model_dump_json()
    second = explain_decision(list(b2), "dec-0003").model_dump_json()

    assert first == second


async def test_every_id_in_an_explanation_resolves_or_is_listed_unresolved(b2):
    everything = {row["subject"] for row in b2 if row.get("subject")} | {row["data"].get("verdict_id") for row in b2} | {
        row["data"].get("decision_id") for row in b2}
    for decision in sorted({row["data"]["decision_id"] for row in b2 if row["type"] == "brain.decision.made"}):
        e = explain_decision(b2, decision)
        assert e.unresolved == [], (decision, e.unresolved)
        for step in e.steps:
            for item in step.ids:
                assert item in everything or item.startswith(("inc-", "dec-")), (decision, item)

    forged = [dict(row) for row in b2]
    made = next(row for row in forged if row["type"] == "brain.decision.made")
    made["data"] = {**made["data"], "evidence": [*made["data"]["evidence"], "ghost-sensor#9"]}
    assert explain_decision(forged, made["data"]["decision_id"]).unresolved == ["ghost-sensor#9"]


async def test_an_explanation_carries_no_demographic_field(b2, b3):
    banned = {"age", "wealth", "income", "gender", "ethnicity", "religion", "nationality"}

    def keys(value):
        if isinstance(value, dict):
            for k, v in value.items():
                yield k.lower()
                yield from keys(v)
        elif isinstance(value, list):
            for item in value:
                yield from keys(item)

    for log, decision in ((b2, "dec-0001"), (b2, "dec-0003")):
        assert not banned & set(keys(json.loads(explain_decision(log, decision).model_dump_json())))
    held = next(row for row in b3 if row["type"] == "brain.action.blocked")
    assert not banned & set(keys(json.loads(explain_held(b3, held["id"]).model_dump_json())))


async def test_an_explanation_builds_from_a_saved_log_with_no_live_graph(tmp_path):
    result = await run("t14", log_dir=tmp_path)
    saved = read_log(result.log_path)

    live = explain_decision([e.model_dump(mode="json") for e in result.sink.events], "dec-0001")
    restored = explain_decision(saved, "dec-0001")

    assert [s.fact for s in restored.steps] == [s.fact for s in live.steps]
    assert restored.log_chain_head == saved[-1]["hash"] and live.log_chain_head == ""


async def test_an_unknown_decision_is_an_error_the_caller_can_catch(b2):
    with pytest.raises(KeyError):
        explain_decision(b2, "dec-9999")


async def test_an_incident_explanation_tells_the_whole_story_and_how_it_ended(b2):
    e = explain_incident(b2, "inc-0001")

    assert e.subject == "incident" and e.outcome == "closed"
    assert types(e).count("brain.decision.made") == 6 and "brain.incident.closed" in types(e)
    assert "apprehended" in e.headline and "6 actions" in e.headline


async def test_margins_say_how_close_a_threshold_was(b2):
    e = explain_decision(b2, "dec-0001")

    names = {m.name for m in e.margins}
    assert {"suspect score", "salience", "independent sources", "actions in the incident"} <= names
    score = next(m for m in e.margins if m.name == "suspect score")
    assert score.threshold == 0.8 and score.observed > score.threshold and "above" in score.how_close


async def test_a_log_from_before_the_gate_recorded_its_facts_still_says_how_many_sources_were_missing(b11):
    held = next(row for row in b11 if row["type"] == "brain.action.blocked")
    old = [dict(row) for row in b11]
    for row in old:
        if row["type"] == "brain.action.blocked":
            row["data"] = {k: v for k, v in row["data"].items() if k not in ("gate", "evidence", "trust_ref")}

    e = explain_held(old, held["id"])

    assert [c.check for c in e.checks] == ["evidence"]
    assert e.counterfactuals[0].change == "A second independent trusted source (1 found, 2 needed)"


async def test_a_team_decision_says_how_each_playbook_item_was_found(b2):
    team = next(row["data"]["decision_id"] for row in b2 if row["type"] == "brain.decision.made" and row["data"]["tier"] == "deliberate")

    e = explain_decision(b2, team)

    found = {k.id: k.why for k in e.knowledge if k.id.startswith("POL-PB")}
    assert found and all(why and why[0].startswith("found by") for why in found.values()), found
    assert any("vector" in w or "keyword" in w for why in found.values() for w in why)
    assert any("for the question" in w for why in found.values() for w in why)


async def test_the_plan_event_records_what_the_team_asked_the_knowledge_base_and_what_came_back(b2):
    plan = next(row for row in b2 if row["type"] == "brain.plan.verified")

    retrieval = plan["data"]["retrieval"]

    assert retrieval and all({"query", "hits", "dropped"} <= set(r) for r in retrieval)
    assert all({"id", "why", "score"} <= set(hit) for r in retrieval for hit in r["hits"])
    assert {"POL-PB-002", "POL-PB-006"} <= {hit["id"] for r in retrieval for hit in r["hits"]}


