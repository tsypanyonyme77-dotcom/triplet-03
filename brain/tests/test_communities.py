"""Global questions: groups of procedures with a summary written by code, never by a model."""

import httpx
import pytest

from brain.api import Hub, create_app
from brain.config import GatePolicy, ModelsConfig, PartnersConfig, Policy
from brain.knowledge.communities import communities, search_global
from brain.knowledge.embedding import HashingEmbedder, make_embedder
from brain.knowledge.graph import build_graph
from tests.test_corpus import DEPARTMENTS, all_playbooks

REAL = ModelsConfig.model_validate({"embeddings": {"provider": "fastembed"}})


def groups():
    return communities(build_graph(all_playbooks()), all_playbooks(), impact=GatePolicy().impact)


def test_each_department_forms_a_community_of_its_own_procedures():
    found = groups()

    assert {c.department for c in found} == set(DEPARTMENTS)
    for community in found:
        mine = {i.id for i in all_playbooks() if i.department == community.department}
        assert set(community.items) == mine and community.items == sorted(community.items)
        assert set(community.incident_types) >= set(DEPARTMENTS[community.department].split())  # an item may also apply to a neighbour's kind


def test_each_community_summary_names_only_items_that_exist():
    known = {i.id for i in all_playbooks()}
    for community in groups():
        mentioned = {word.strip("(),.;:") for word in community.summary.split() if "-PB-" in word}
        assert mentioned <= known and mentioned <= set(community.items), community.id
        assert community.summary.startswith(f"{community.name} ") and "procedure" in community.summary


def test_what_is_blocked_is_computed_from_the_gate_policy_and_the_actions_the_items_use():
    utilities = next(c for c in groups() if c.department == "UTILITIES")
    disaster = next(c for c in groups() if c.department == "DISASTER")
    police = next(c for c in groups() if c.department == "POLICE")

    assert "Held for a human approval: set_grid_connection (UTL-PB-006)" in utilities.summary
    assert "Held for a human approval: set_valve_state (UTL-PB-002, UTL-PB-003)" in disaster.summary
    assert "Held for a human approval" not in police.summary and "No procedure here is held" in police.summary
    assert utilities.held == {"set_grid_connection": ["UTL-PB-006"]}
    assert disaster.held == {"set_valve_state": ["UTL-PB-002", "UTL-PB-003"]}


def test_a_global_question_returns_the_department_it_is_about():
    found = groups()
    embedder, note = make_embedder("fastembed")  # a bag-of-words embedder gets three of these four wrong: global questions need the real model

    expected = {
        "What can the Brain do about flooding, and what is blocked?": "DISASTER",
        "How does the Brain respond to a robbery and a suspect on the run?": "POLICE",
        "What happens when a fire is reported?": "FIRE",
        "How does the Brain clear a traffic jam?": "MOBILITY",
    }
    for question, department in expected.items():
        assert search_global(question, found, embedder, k=1)[0].department == department, question
    assert len(search_global("anything", found, HashingEmbedder(), k=2)) == 2 and search_global("anything", [], embedder) == []


@pytest.fixture
async def api(tmp_path):
    hub = Hub(PartnersConfig(), Policy(), REAL, mocks="inproc", log_dir=tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(hub)), base_url="http://brain") as client:
        yield client, hub


async def test_the_api_answers_a_global_question(api):
    client, hub = api
    assert (await client.get("/api/knowledge/global", params={"question": "flooding"})).status_code == 404  # no run yet

    await client.post("/api/scenarios/d1/run", params={"speed": 0})
    await hub.wait()

    body = (await client.get("/api/knowledge/global", params={"question": "What can the Brain do about flooding, and what is blocked?", "k": 1})).json()
    assert [c["department"] for c in body["communities"]] == ["DISASTER"] and "set_valve_state" in body["communities"][0]["summary"]
