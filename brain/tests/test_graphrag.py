"""GraphRAG: seeds from the hybrid search, then the authored links walked a bounded way, every hit carrying the path that brought it."""

import os

import pytest

from brain.config import KnowledgeConfig
from brain.knowledge import KnowledgeItem
from brain.knowledge.embedding import HashingEmbedder, tokens
from brain.knowledge.graph import build_graph, expand
from brain.knowledge.memory import MemoryKnowledgeBase
from tests.test_neo4j import URI, needs_neo4j


def item(id, title, text, uses=(), **links):
    return KnowledgeItem(id=id, kind="playbook", title=title, text=text, department="D", applies_to=["flood"], uses=list(uses), **links)


# A small world with a known shape: VALVE needs a person and a right valve, ALERT can stand in for VALVE, STEPA precedes STEPB precedes STEPC.
ITEMS = [
    item("VALVE", "Close the harbour valve when the river floods", "valve close river flood harbour", uses=["set_valve_state"], requires=["APPROVAL"], escalates_to=["SIREN"]),
    item("APPROVAL", "A person must approve", "human approval person agree sign off"),
    item("ALERT", "Warn the zone", "alert warn zone broadcast residents", uses=["broadcast_alert"], substitutes=["VALVE"]),
    item("SIREN", "Sound the sirens", "siren loud warning escalate", uses=["broadcast_alert"]),
    item("STEPA", "First step to take", "alpha first begin start", precedes=["STEPB"]),
    item("STEPB", "Second step to take", "bravo second follow next", precedes=["STEPC"]),
    item("STEPC", "Third step to take", "charlie third final last"),
    item("NOISE", "Unrelated thing", "completely different subject matter"),
    item("CLASH", "Do the opposite of closing the valve", "valve close river flood opposite", conflicts_with=["VALVE"]),
]
ITEMS[0] = ITEMS[0].model_copy(update={"conflicts_with": ["CLASH"]})


class VocabEmbedder:
    """Normalised word counts over the items' own vocabulary: a word the query shares with an item is the only thing that makes them
    similar, so which items a search seeds is exactly what the test says it is."""

    name = "vocab"

    def __init__(self, texts):
        words = sorted({w for t in texts for w in tokens(t)})
        self.index, self.dimensions = {w: i for i, w in enumerate(words)}, len(words)

    def embed(self, texts):
        out = []
        for text in texts:
            vector = [0.0] * self.dimensions
            for word in tokens(text):
                if word in self.index:
                    vector[self.index[word]] += 1.0
            norm = sum(v * v for v in vector) ** 0.5 or 1.0
            out.append([v / norm for v in vector])
        return out


def vocab():
    return VocabEmbedder([i.content for i in ITEMS])


@pytest.fixture
async def kb():
    base = MemoryKnowledgeBase(vocab(), KnowledgeConfig(graphrag="local"))
    await base.sync(ITEMS)
    return base


def test_expansion_follows_each_relation_the_way_it_points():
    graph = build_graph(ITEMS)

    found = {(e.seed, e.item, e.group): [(s.from_id, s.rel, s.to_id) for s in e.path] for e in expand(graph, ["VALVE"], 2)}

    assert found[("VALVE", "APPROVAL", "onward")] == [("VALVE", "REQUIRES", "APPROVAL")]
    assert found[("VALVE", "SIREN", "onward")] == [("VALVE", "ESCALATES_TO", "SIREN")]
    assert found[("VALVE", "ALERT", "stand-in")] == [("ALERT", "SUBSTITUTES", "VALVE")]  # real edge direction: the stand-in substitutes
    assert ("VALVE", "CLASH", "onward") not in found  # a conflict is never walked into
    two = {(e.item, e.group): len(e.path) for e in expand(graph, ["STEPA"], 2)}
    assert two == {("STEPB", "onward"): 1, ("STEPC", "onward"): 2}
    assert {(e.item, e.group): len(e.path) for e in expand(graph, ["STEPC"], 2)} == {("STEPB", "before"): 1, ("STEPA", "before"): 2}


def test_expansion_is_bounded_deterministic_and_never_loops_back_to_the_seed():
    cyclic = build_graph([item("X", "x", "x", precedes=["Y"]), item("Y", "y", "y", precedes=["X"])])

    one = expand(cyclic, ["X"], 5)

    assert {(e.item, e.group, len(e.path)) for e in one} == {("Y", "onward", 1), ("Y", "before", 1)}  # reached two ways, never X itself
    assert one == expand(cyclic, ["X"], 5)
    assert expand(build_graph(ITEMS), ["STEPA"], 1) and all(len(e.path) <= 1 for e in expand(build_graph(ITEMS), ["STEPA"], 1))


async def test_a_two_hop_item_is_found_with_its_path():
    steady = MemoryKnowledgeBase(vocab(), KnowledgeConfig(graphrag="local", decay=0.9))  # a gentle decay: the second step still beats a filler seed
    await steady.sync(ITEMS)
    hits = await steady.search("alpha first begin start", department="D", k=3)

    by_id = {h.id: h for h in hits}
    assert by_id["STEPA"].path is None  # a seed has no path: it was found by search
    assert [(s.from_id, s.rel, s.to_id) for s in by_id["STEPC"].path] == [("STEPA", "PRECEDES", "STEPB"), ("STEPB", "PRECEDES", "STEPC")]
    assert "graph:precedes" in by_id["STEPC"].why and by_id["STEPB"].score > by_id["STEPC"].score


async def test_expansion_never_returns_an_item_the_twin_cannot_carry_out(kb):
    hits = await kb.search("close the valve when the river floods", department="D", available_actions={"set_valve_state"}, k=6)
    assert "VALVE" in [h.id for h in hits]  # the search finds it, and the Twin can do it
    assert all(h.id not in {"ALERT", "SIREN"} for h in hits)  # both need broadcast_alert, which this Twin does not report


def test_a_stand_in_is_offered_when_the_seed_it_replaces_is_unusable():
    from brain.knowledge import fuse_traced

    items = {i.id: i for i in ITEMS}
    seeds = {"VALVE": 0.0328}  # the search found only the valve procedure, which this Twin cannot carry out
    walk = expand(build_graph(ITEMS), ["VALVE"], 2)

    hits, trace = fuse_traced(items, ["VALVE"], ["VALVE"], incident_type=None, department="D", available_actions={"broadcast_alert"}, k=3,
                              expansions=walk, seed_scores=seeds)

    assert ("VALVE", "needs set_valve_state, which the Twin does not report") in trace.dropped and "VALVE" not in [h.id for h in hits]
    assert [h.id for h in hits] == ["ALERT"]  # VALVE requires APPROVAL and escalates to SIREN, but it cannot be done: only its stand-in comes through
    assert [(s.from_id, s.rel, s.to_id) for s in hits[0].path] == [("ALERT", "SUBSTITUTES", "VALVE")]
    assert hits[0].why == ["graph:substitutes"] and hits[0].score == round(0.0328 * 0.5, 5)


async def test_an_item_the_search_found_keeps_its_score_and_has_no_path(kb):
    hits = await kb.search("close the valve when the river floods", department="D", available_actions={"broadcast_alert"}, k=3)

    assert all(h.path is None for h in hits)  # the search found every one of them itself, so the walk has nothing to say about them


async def test_a_conflicting_item_is_demoted_and_says_so_when_the_penalty_is_on():
    kb = MemoryKnowledgeBase(vocab(), KnowledgeConfig(graphrag="local", conflict_penalty=0.5))
    await kb.sync(ITEMS)
    off = MemoryKnowledgeBase(vocab(), KnowledgeConfig(graphrag="off"))
    await off.sync(ITEMS)
    question = "close the valve when the river floods"

    plain = {h.id: h.score for h in await off.search(question, department="D", k=6)}
    graph = {h.id: h for h in await kb.search(question, department="D", k=6)}

    lower = min(("VALVE", "CLASH"), key=lambda i: plain[i])
    assert graph[lower].score < plain[lower]
    assert any(w.startswith("graph:conflicts_with") for w in graph[lower].why)


async def test_by_default_a_conflict_costs_nothing(kb):
    hits = await kb.search("close the valve when the river floods", department="D", k=6)

    assert not any(w.startswith("graph:conflicts_with") for h in hits for w in h.why)


async def test_the_walk_brings_in_what_the_search_missed_and_does_not_re_rank_what_it_found():
    plain, walking = (MemoryKnowledgeBase(vocab(), KnowledgeConfig(graphrag=mode, decay=0.9)) for mode in ("off", "local"))
    for base in (plain, walking):
        await base.sync(ITEMS)

    a = await plain.search("alpha first begin start", department="D", k=3)
    b = await walking.search("alpha first begin start", department="D", k=3)

    found = {h.id: h.score for h in a if "graph:" not in "".join(h.why)}
    assert all(h.score == found[h.id] for h in b if h.id in found)  # a found item keeps its search score exactly


async def test_graphrag_off_returns_exactly_todays_hits():
    off = MemoryKnowledgeBase(vocab(), KnowledgeConfig())
    explicit = MemoryKnowledgeBase(vocab(), KnowledgeConfig(graphrag="off"))
    for base in (off, explicit):
        await base.sync(ITEMS)

    for question in ("alpha first begin start", "close the valve", "warn the zone"):
        a, b = await off.search(question, department="D", k=5), await explicit.search(question, department="D", k=5)
        assert [(h.id, h.score, h.why) for h in a] == [(h.id, h.score, h.why) for h in b]
        assert all(h.path is None for h in a)


@needs_neo4j
async def test_memory_and_neo4j_walk_the_links_to_the_same_items_by_the_same_paths():
    from brain.citygraph.neo4j import Neo4jMirror
    from brain.knowledge.neo4j import Neo4jKnowledgeBase

    mirror = Neo4jMirror(URI, "neo4j", os.environ["NEO4J_PASSWORD"], "neo4j", "test-graphrag")
    await mirror.connect()
    try:
        renamed = [i.model_copy(update={f: [f"GR-{x}" for x in getattr(i, f)] for f in ("requires", "precedes", "escalates_to", "conflicts_with", "substitutes")} | {"id": f"GR-{i.id}", "department": "GRD", "applies_to": ["gr-flood"]}) for i in ITEMS]
        options = KnowledgeConfig(graphrag="local")
        graph = Neo4jKnowledgeBase(mirror, HashingEmbedder(), options)
        await graph.sync(renamed)
        # The walks themselves must be the same, whichever search seeded them.
        walk = lambda found: [(e.seed, e.item, e.group, [(s.from_id, s.rel, s.to_id) for s in e.path]) for e in found]  # noqa: E731
        for seeds in (["GR-VALVE"], ["GR-STEPA"], ["GR-STEPC", "GR-ALERT"], ["GR-VALVE", "GR-STEPA", "GR-CLASH", "GR-NOISE"]):
            for hops in (1, 2, 3):
                assert walk(await graph._expand(seeds, hops)) == walk(expand(build_graph(renamed), seeds, hops)), (seeds, hops)
    finally:
        await mirror.query("MATCH (k:Knowledge) WHERE k.id STARTS WITH 'GR-' DETACH DELETE k")
        await mirror.query("MATCH (n) WHERE (n:IncidentType AND n.name = 'gr-flood') OR (n:Department AND n.id = 'GRD') DETACH DELETE n")
        await mirror.query("MATCH (n:ActionType) WHERE n.name IN ['set_valve_state', 'broadcast_alert'] AND NOT (n)<-[:USES]-() DETACH DELETE n")
        await mirror.close()
