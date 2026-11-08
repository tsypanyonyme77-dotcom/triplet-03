"""The explanation as W3C PROV-JSON: every step an activity, every relation pointing at something defined, the same bytes for the same log."""

import json

from brain.config import ModelsConfig, Policy
from brain.explain import explain_decision
from brain.explain.prov import PREFIXES, to_prov
from brain.scenario import inproc_partners, load_scenario, run_scenario

MODELS = ModelsConfig.model_validate({"embeddings": {"provider": "hashing"}})


async def explained():
    result = await run_scenario(load_scenario("d3"), inproc_partners(), models=MODELS, speed=0, timeout_s=30, deterministic=True)
    events = [e.model_dump(mode="json", exclude_none=True) for e in result.sink.events]
    decision = next(e for e in events if e["type"] == "brain.decision.made")["data"]["decision_id"]
    return explain_decision(events, decision, policy=Policy())


async def test_every_step_of_an_explanation_becomes_an_activity():
    e = await explained()
    prov = to_prov(e)

    assert len(prov["activity"]) == len(e.steps) and set(prov["prefix"]) == set(PREFIXES)
    assert {"twin", "guardian", "city_brain"} <= {a["brain:layer"] if a.get("brain:layer") != "brain" else "city_brain" for a in prov["agent"].values()}


async def test_every_relation_points_at_a_defined_node():
    prov = to_prov(await explained())
    defined = set(prov["entity"]) | set(prov["activity"]) | set(prov["agent"])

    for table in ("wasGeneratedBy", "used", "wasAssociatedWith", "wasDerivedFrom", "wasInformedBy"):
        for relation in prov[table].values():
            assert all(value in defined for value in relation.values()), (table, relation)
    assert prov["wasAssociatedWith"] and prov["used"] and prov["wasInformedBy"]


async def test_the_same_log_gives_the_same_bytes():
    first, second = to_prov(await explained()), to_prov(await explained())

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)


async def test_the_gate_checks_are_attached_to_the_decision_activity():
    prov = to_prov(await explained())

    assert any("brain:gate_checks" in a for a in prov["activity"].values())
