"""The links between procedures: written by hand in the playbooks, checked on load, and the graph holds exactly those and no others."""

import os
from collections import Counter

from brain.knowledge import KnowledgeItem, load_playbook
from brain.knowledge.embedding import HashingEmbedder
from brain.knowledge.graph import LINKS, build_graph, check_links
from tests.test_corpus import DEPARTMENTS, all_playbooks
from tests.test_neo4j import URI, needs_neo4j


def item(id, **links):
    return KnowledgeItem(id=id, kind="playbook", title=id, text=f"text of {id}", department="D", applies_to=["flood"], uses=["broadcast_alert"], **links)


def test_a_link_to_an_unknown_item_is_reported_and_dropped_and_the_item_stays():
    items = [item("A", requires=["B", "GHOST"], precedes=["A"]), item("B", conflicts_with=["A"])]

    kept, problems = check_links(items)

    assert [i.id for i in kept] == ["A", "B"]
    assert kept[0].requires == ["B"] and kept[0].precedes == []
    assert kept[1].conflicts_with == []  # A does not list B back, so the pair is not a conflict
    assert any("GHOST" in p and "A" in p for p in problems) and any("itself" in p for p in problems) and any("symmetric" in p for p in problems)


def test_a_conflict_listed_on_both_sides_is_kept():
    kept, problems = check_links([item("A", conflicts_with=["B"]), item("B", conflicts_with=["A"])])

    assert problems == [] and kept[0].conflicts_with == ["B"] and kept[1].conflicts_with == ["A"]


def test_the_shipped_playbooks_have_no_broken_link_and_every_conflict_is_symmetric():
    for code in DEPARTMENTS:
        _, problems = check_links(load_playbook(code))
        assert problems == [], (code, problems)


def test_the_shipped_playbooks_are_linked_but_not_over_linked():
    items = all_playbooks()
    counts = [sum(len(getattr(i, rel)) for rel in LINKS) for i in items]

    assert sum(1 for n in counts if n) >= len(items) * 0.6  # most procedures are connected to another (mobility's are mostly stand-alone)
    assert max(counts) <= 5 and sum(counts) <= 3 * len(items)


def test_the_graph_has_no_edge_the_yaml_did_not_author():
    items = all_playbooks()
    graph = build_graph(items)

    wanted = Counter()
    for i in items:
        wanted.update(("item:" + i.id, "APPLIES_TO", "incident_type:" + t) for t in i.applies_to)
        wanted.update(("item:" + i.id, "USES", "action:" + a) for a in i.uses)
        wanted.update(("item:" + i.id, "BELONGS_TO", "department:" + i.department) for _ in [0] if i.department)
        for rel, name in LINKS.items():
            wanted.update(("item:" + i.id, name, "item:" + other) for other in getattr(i, rel))
    found = Counter((f"{u[0]}:{u[1]}", data["rel"], f"{v[0]}:{v[1]}") for u, v, data in graph.edges(data=True))

    assert found == wanted


def test_a_substitute_is_an_edge_from_the_stand_in_to_what_it_stands_in_for():
    graph = build_graph(all_playbooks())

    assert graph.has_edge(("item", "UTL-PB-001"), ("item", "UTL-PB-002"))
    assert "SUBSTITUTES" in [d["rel"] for d in graph.get_edge_data(("item", "UTL-PB-001"), ("item", "UTL-PB-002")).values()]
    assert graph.has_edge(("item", "POL-PB-004"), ("item", "POL-PB-003"))


@needs_neo4j
async def test_the_links_are_relationships_in_neo4j_and_a_changed_link_replaces_the_old_one():
    from brain.citygraph.neo4j import Neo4jMirror
    from brain.knowledge.neo4j import Neo4jKnowledgeBase

    mirror = Neo4jMirror(URI, "neo4j", os.environ["NEO4J_PASSWORD"], "neo4j", "test-links")
    await mirror.connect()
    try:
        kb = Neo4jKnowledgeBase(mirror, HashingEmbedder())
        first = [item("TL-A", requires=["TL-B"], substitutes=["TL-C"]), item("TL-B"), item("TL-C")]
        await kb.sync(first)
        rows = await mirror.query("MATCH (a:Knowledge)-[r]->(b:Knowledge) WHERE a.id STARTS WITH 'TL-' RETURN a.id AS a, type(r) AS rel, b.id AS b ORDER BY rel")
        assert [(r["a"], r["rel"], r["b"]) for r in rows] == [("TL-A", "REQUIRES", "TL-B"), ("TL-A", "SUBSTITUTES", "TL-C")]

        await kb.sync([item("TL-A", precedes=["TL-B"]), item("TL-B"), item("TL-C")])
        rows = await mirror.query("MATCH (a:Knowledge)-[r]->(b:Knowledge) WHERE a.id STARTS WITH 'TL-' RETURN a.id AS a, type(r) AS rel, b.id AS b")
        assert [(r["a"], r["rel"], r["b"]) for r in rows] == [("TL-A", "PRECEDES", "TL-B")]
    finally:
        await mirror.query("MATCH (k:Knowledge) WHERE k.id STARTS WITH 'TL-' DETACH DELETE k")
        await mirror.query("MATCH (n) WHERE (n:IncidentType AND n.name = 'flood') AND NOT (n)<-[:APPLIES_TO]-() DETACH DELETE n")
        await mirror.query("MATCH (n:ActionType {name: 'broadcast_alert'}) WHERE NOT (n)<-[:USES]-() DETACH DELETE n")
        await mirror.query("MATCH (d:Department {id: 'D'}) DETACH DELETE d")
        await mirror.close()


async def test_a_bad_link_in_a_playbook_is_reported_when_the_brain_starts_and_the_item_stays(monkeypatch):
    from brain import runtime
    from brain.config import ModelsConfig
    from brain.knowledge.memory import MemoryKnowledgeBase
    from brain.scenario import inproc_partners, load_scenario, run_scenario

    real = runtime.load_playbook
    monkeypatch.setattr(runtime, "load_playbook", lambda code: [i.model_copy(update={"requires": ["GHOST-1"]}) if i.id == "POL-PB-001" else i for i in real(code)])
    kb = MemoryKnowledgeBase(HashingEmbedder())

    result = await run_scenario(load_scenario("d1"), inproc_partners(), models=ModelsConfig.model_validate({"embeddings": {"provider": "hashing"}}),
                                speed=0, timeout_s=30, kb=kb)

    reports = [e for e in result.sink.events if e.type == "brain.pack.rejected"]
    assert any(e.data["file"] == "playbooks" and "GHOST-1" in e.data["reason"] and "the item stays" in e.data["reason"] for e in reports)
    assert kb.has("POL-PB-001") and kb.items["POL-PB-001"].requires == []
