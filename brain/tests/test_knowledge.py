"""Retrieval that can say how it chose: which signals found an item, at what rank, and what was set aside and why."""

import os

import pytest

from brain.config import KnowledgeConfig
from brain.knowledge import KnowledgeItem
from brain.knowledge.embedding import HashingEmbedder
from brain.knowledge.memory import MemoryKnowledgeBase
from tests.test_neo4j import URI, needs_neo4j


def item(id, title, text, department="DEPT", applies_to=("flood",), uses=(), kind="playbook", helpful=0, harmful=0):
    return KnowledgeItem(id=id, kind=kind, title=title, text=text, department=department, applies_to=list(applies_to), uses=list(uses),
                         helpful=helpful, harmful=harmful)


ITEMS = [
    item("A-1", "Close the harbour valve when the river rises", "Ask to close the valve when the water level passes the flood mark.", uses=["set_valve_state"]),
    item("A-2", "Warn people near the river", "Broadcast an alert asking people to avoid low roads by the river.", uses=["broadcast_alert"]),
    item("A-3", "Warn people near the river banks", "Broadcast an alert asking people to avoid low roads by the river banks.", uses=["broadcast_alert"]),
    item("A-4", "Send a fire engine", "Dispatch the nearest fire engine to a building fire.", applies_to=("fire",), uses=["dispatch_unit"]),
    item("B-1", "Another department's flood note", "The water level and the river valve, for the other department.", department="OTHER"),
]


@pytest.fixture
async def kb():
    base = MemoryKnowledgeBase(HashingEmbedder())
    await base.sync(ITEMS)
    return base


async def test_a_hit_says_which_signals_found_it_and_at_what_rank(kb):
    hits, trace = await kb.search_traced("close the valve, the river water level is rising", department="DEPT", k=3)

    assert hits[0].id == "A-1" and set(hits[0].why) >= {"vector", "keyword"}
    ranked = {signal: [(i, rank) for i, rank, _ in rows] for signal, rows in trace.signals.items()}
    assert ranked["vector"][0] == ("A-1", 1) and ranked["keyword"][0] == ("A-1", 1)
    assert all(score > 0 for _, _, score in trace.signals["keyword"])
    assert trace.fused == [h.id for h in hits] and hits[0].trace is trace and trace.query.startswith("close the valve")


async def test_a_playbook_item_that_needs_a_missing_actuator_is_dropped_with_its_reason(kb):
    hits, trace = await kb.search_traced("close the valve when the river rises", department="DEPT", available_actions={"broadcast_alert"}, k=3)

    assert "A-1" not in [h.id for h in hits]
    assert ("A-1", "needs set_valve_state, which the Twin does not report") in trace.dropped
    assert ("B-1", "belongs to OTHER, not DEPT") in trace.dropped


async def test_a_search_with_nothing_usable_still_explains_itself(kb):
    hits, trace = await kb.search_traced("close the valve", department="NOBODY", kinds={"rule"}, k=3)

    assert hits == [] and trace.fused == [] and {i for i, _ in trace.dropped} >= {"A-1", "B-1"}
    assert any(reason == "is a playbook, not a rule" for _, reason in trace.dropped)


async def test_the_filters_come_before_the_cut_so_a_big_corpus_cannot_crowd_out_the_right_items():
    base = MemoryKnowledgeBase(HashingEmbedder())
    crowd = [item(f"X-{n}", "Close the harbour valve when the river rises", "valve river water level flood mark", department="OTHER")
             for n in range(20)]
    await base.sync([*crowd, ITEMS[0]])

    hits = await base.search("close the valve, the river water level is rising", department="DEPT", k=3)

    assert [h.id for h in hits] == ["A-1"]


async def test_mmr_removes_a_near_duplicate_without_losing_the_best_item():
    plain = MemoryKnowledgeBase(HashingEmbedder())
    varied = MemoryKnowledgeBase(HashingEmbedder(), KnowledgeConfig(mmr=0.7))
    for base in (plain, varied):
        await base.sync(ITEMS)

    question = "warn people near the river and close the valve"
    first = [h.id for h in await plain.search(question, department="DEPT", k=3)]
    second = [h.id for h in await varied.search(question, department="DEPT", k=3)]

    assert set(first[:2]) >= {"A-2", "A-3"} or {"A-2", "A-3"} <= set(first)  # the twins rank together without it
    assert second[0] == first[0] and not {"A-2", "A-3"} <= set(second[:2])  # with it, a twin gives way to a different item


async def test_utility_weight_zero_leaves_the_ranking_unchanged_and_a_positive_weight_prefers_what_helped():
    liked = [i.model_copy(update={"helpful": 9} if i.id == "A-3" else {}) for i in ITEMS]
    off, on = MemoryKnowledgeBase(HashingEmbedder()), MemoryKnowledgeBase(HashingEmbedder(), KnowledgeConfig(utility_weight=1.0))
    reference = MemoryKnowledgeBase(HashingEmbedder())
    await off.sync(liked)
    await on.sync(liked)
    await reference.sync(ITEMS)

    question = "warn people near the river"
    assert [h.id for h in await off.search(question, department="DEPT", k=4)] == [h.id for h in await reference.search(question, department="DEPT", k=4)]
    boosted = [h.id for h in await on.search(question, department="DEPT", k=4)]
    assert boosted.index("A-3") < boosted.index("A-2")


@needs_neo4j
async def test_the_two_backends_return_the_same_top_hit_and_the_same_set_for_the_same_query():
    from brain.citygraph.neo4j import Neo4jMirror
    from brain.knowledge.neo4j import Neo4jKnowledgeBase

    mirror = Neo4jMirror(URI, "neo4j", os.environ["NEO4J_PASSWORD"], "neo4j", "test-parity")
    await mirror.connect()
    try:
        items = [i.model_copy(update={"id": f"TP-{i.id}", "department": "TPDEPT" if i.department == "DEPT" else "TPOTHER",
                                      "applies_to": [f"tp-{t}" for t in i.applies_to]}) for i in ITEMS]
        graph, memory = Neo4jKnowledgeBase(mirror, HashingEmbedder()), MemoryKnowledgeBase(HashingEmbedder())
        await graph.sync(items)
        await memory.sync(items)
        for question in ("close the valve, the river water level is rising", "warn people near the river", "send a fire engine"):
            a = await graph.search(question, incident_type="tp-flood", department="TPDEPT", k=4)
            b = await memory.search(question, incident_type="tp-flood", department="TPDEPT", k=4)
            # The order of weak, near-tied matches may differ: Neo4j's full-text index scores with Lucene, the memory side with its own BM25.
            assert a[0].id == b[0].id and {h.id for h in a} == {h.id for h in b}, question
    finally:
        await mirror.query("MATCH (k:Knowledge) WHERE k.id STARTS WITH 'TP-' DETACH DELETE k")
        await mirror.query("MATCH (n) WHERE (n:IncidentType AND n.name STARTS WITH 'tp-') OR (n:Department AND n.id STARTS WITH 'TP') DETACH DELETE n")
        await mirror.close()


def test_incident_questions_are_deterministic_short_and_name_the_incident_and_the_zone():
    from brain.knowledge.query import incident_questions

    first = incident_questions("flood", "Harbor", {"set_valve_state", "broadcast_alert", "dispatch_unit"})

    assert first == incident_questions("flood", "Harbor", {"dispatch_unit", "broadcast_alert", "set_valve_state"})  # order of a set is not input
    assert 2 <= len(first) <= 4 and all("flood" in q and q.endswith("?") for q in first)
    assert any("Harbor" in q for q in first) and any("broadcast alert" in q for q in first)
    assert incident_questions("jam", None, set())[0] == "What should be done about a jam?"
