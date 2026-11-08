"""The Analyst's three new tools: the city around the incident, similar past stories, and a search that walks the playbooks' links.
All read-only, off by default, and small enough for a free-plan token budget."""

import json

from brain.config import KnowledgeConfig, ModelsConfig, Policy
from brain.departments import load_manifest
from brain.departments.builder import role_tools
from brain.departments.team import TOOL_DESCRIPTIONS, ToolBox
from brain.knowledge import load_playbook
from brain.knowledge.embedding import HashingEmbedder
from brain.knowledge.memory import MemoryKnowledgeBase
from brain.scenario import load_scenario
from tests.test_episodic import STORIES
from tests.test_team import desk, modes, play  # noqa: F401  (fixtures and helpers)

POLICY = Policy()
NEW = ["graph.context", "episodes.similar", "kb.graph_search"]


def with_switch(on: bool, **more) -> ModelsConfig:
    return ModelsConfig.model_validate({"embeddings": {"provider": "hashing"}, "knowledge": {"team_tools": on, **more}})


def test_the_new_tools_go_to_the_analyst_only_when_the_switch_is_on():
    manifest = load_manifest("police")

    off, on = role_tools(manifest, with_switch(False)), role_tools(manifest, with_switch(True))

    assert not set(NEW) & {t for tools in off.values() for t in tools}
    assert set(NEW) <= set(on["analyst"]) and on["tactician"] == off["tactician"] and on["chief"] == off["chief"]
    assert on["analyst"][: len(off["analyst"])] == off["analyst"]  # what it had, in the order it had it
    assert all(name in TOOL_DESCRIPTIONS for name in NEW)


async def graph_box(world, incident, stories=None):
    kb = MemoryKnowledgeBase(HashingEmbedder(), KnowledgeConfig(graphrag="local"))
    await kb.sync(load_playbook("POLICE"))
    return ToolBox(world.store, kb, POLICY, incident, "POLICE", {"dispatch_unit", "broadcast_alert"}, "cit-1",
                   stories=(lambda: stories) if stories is not None else None, embedder=HashingEmbedder())


async def test_the_new_tools_only_read(desk):
    world, incident, _ = desk
    world.store.commit_unit("police-dispatch-05", "unit-p-01", incident_id="inc-0001", mode="respond", zone_id="zone-07")
    tools = await graph_box(world, incident, STORIES)
    before = (sorted(map(str, world.store.g.nodes)), sorted(map(str, world.store.g.edges(keys=True))), world.store.snapshot())

    await tools.graph_context()
    await tools.episodes_similar()
    await tools.kb_graph_search("seal the suspect in")

    assert (sorted(map(str, world.store.g.nodes)), sorted(map(str, world.store.g.edges(keys=True))), world.store.snapshot()) == before
    assert not hasattr(tools, "gate") and [c["tool"] for c in tools.calls] == ["graph.context", "episodes.similar", "kb.graph_search"]


async def test_the_city_context_tool_names_zones_and_no_person(desk):
    world, incident, _ = desk
    world.store.commit_unit("police-dispatch-05", "unit-p-01", incident_id="inc-0001", mode="pursuit", zone_id="zone-07", target_id="cit-2")
    tools = await graph_box(world, incident)

    result = await tools.graph_context()

    assert result["incident"] == "crime in Downtown" and result["units_out"] == {"pursuit": 1}
    assert {n["type"] for n in result["nearest_facilities"]} >= {"police_station", "fire_station", "hospital"}
    assert result["zones_within_2_hops"] and "cit-2" not in json.dumps(result)


async def test_similar_stories_carry_no_outcome_and_say_when_there_are_none(desk):
    world, incident, _ = desk

    some = await (await graph_box(world, incident, STORIES)).episodes_similar()
    none = await (await graph_box(world, incident)).episodes_similar()

    assert 1 <= len(some["stories"]) <= 3 and all(s["incident_type"] == "crime" for s in some["stories"])
    assert "apprehended" not in json.dumps(some) and "never evidence" in some["note"]
    assert none == {"stories": [], "note": "the Brain keeps no past stories to compare with"}


async def test_the_graph_search_says_how_each_item_was_reached(desk):
    world, incident, _ = desk
    tools = await graph_box(world, incident)

    found = await tools.kb_graph_search("tight perimeter around the suspect")

    assert found and all({"id", "title", "text", "how"} <= set(item) for item in found)
    assert any(item["how"] != "found by search" and " " in item["how"] for item in found) or all(item["how"] == "found by search" for item in found)


async def test_tool_results_are_capped_to_the_token_budget(desk):
    world, incident, _ = desk
    many = [s for _ in range(12) for s in STORIES]
    tools = await graph_box(world, incident, many)

    for result in (await tools.graph_context(), await tools.episodes_similar(), await tools.kb_graph_search("what should the units do")):
        assert len(json.dumps(result)) <= 2500


async def test_the_scripted_team_decides_the_same_with_the_tools_on():
    plain = await play(load_scenario("d3"), models=with_switch(False))
    equipped = await play(load_scenario("d3"), models=with_switch(True, graphrag="local"))

    assert plain.passed and equipped.passed
    assert [(c["call"]["action"], c["call"]["params"]) for c in plain.actuator_calls] == [(c["call"]["action"], c["call"]["params"]) for c in equipped.actuator_calls]


# ---- the engines as tools

async def test_plan_allocation_is_a_dry_run_and_sends_nothing(desk):
    world, incident, _ = desk
    tools = await graph_box(world, incident)
    before = world.store.snapshot()

    result = await tools.solver_plan_allocation("police")

    assert result["sent"] is False and result["assignment"][incident.incident_id] and world.store.snapshot() == before
    assert [c["tool"] for c in tools.calls] == ["solver.plan_allocation"]
    assert len(json.dumps(result)) / 4 < 400  # a free-plan token budget


async def test_plan_allocation_refuses_a_unit_type_nobody_has(desk):
    world, incident, _ = desk

    assert "error" in await (await graph_box(world, incident)).solver_plan_allocation("tank")


async def test_time_to_threshold_says_so_when_there_are_no_readings(desk):
    world, incident, _ = desk

    assert "no water-level readings" in (await (await graph_box(world, incident)).math_time_to_threshold("wl-99"))["error"]


def test_the_engine_tools_are_registered_and_the_solver_needs_the_analyse_scope():
    from brain.tools.registry import agent_registry

    registry = agent_registry()

    assert registry.get("solver.plan_allocation").scope == "analyse" and registry.get("math.time_to_threshold").scope == "read"
