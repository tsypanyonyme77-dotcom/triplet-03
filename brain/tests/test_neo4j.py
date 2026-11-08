"""Against a real Neo4j. Skipped unless one is reachable:

    NEO4J_PASSWORD=<password> [NEO4J_TEST_URI=bolt://127.0.0.1:7687] uv run pytest tests/test_neo4j.py
"""

import os
import socket
from urllib.parse import urlparse

import pytest

from brain.backends import open_backends
from brain.config import GraphConfig, ModelsConfig
from brain.knowledge import KnowledgeItem
from brain.knowledge.embedding import HashingEmbedder
from brain.scenario import inproc_partners, load_scenario, run_scenario

URI = os.environ.get("NEO4J_TEST_URI", "bolt://127.0.0.1:7687")


def _reachable() -> bool:
    if not os.environ.get("NEO4J_PASSWORD"):
        return False
    target = urlparse(URI)
    try:
        with socket.create_connection((target.hostname, target.port or 7687), timeout=1):
            return True
    except OSError:
        return False


needs_neo4j = pytest.mark.skipif(not _reachable(), reason="no Neo4j reachable (set NEO4J_PASSWORD and start one)")
GRAPH = GraphConfig(backend="neo4j", uri=URI)


async def test_an_unreachable_neo4j_degrades_to_memory_with_a_clear_note():
    nowhere = GraphConfig(backend="neo4j", uri="bolt://127.0.0.1:1", qdrant_location=None)

    async with open_backends(nowhere, ModelsConfig(), "run-x") as backends:
        assert type(backends.store).__name__ == "MemoryGraphStore"
        assert backends.kb is None
        assert "is unavailable" in backends.note and "running in memory" in backends.note


async def test_knowledge_stays_in_qdrant_when_neo4j_is_unreachable():
    nowhere = GraphConfig(backend="neo4j", uri="bolt://127.0.0.1:1", qdrant_location=":memory:")

    async with open_backends(nowhere, ModelsConfig.model_validate({"embeddings": {"provider": "hashing"}}), "run-x") as backends:
        assert type(backends.store).__name__ == "MemoryGraphStore"
        assert type(backends.kb.primary).__name__ == "QdrantKnowledgeBase"
        assert "Neo4j" in backends.note and "running in memory" in backends.note


@needs_neo4j
async def test_knowledge_is_embedded_once_and_retrieved_through_the_indexes():
    from brain.citygraph.neo4j import Neo4jMirror
    from brain.knowledge.neo4j import Neo4jKnowledgeBase

    mirror = Neo4jMirror(URI, "neo4j", os.environ["NEO4J_PASSWORD"], "neo4j", "test-kb")
    await mirror.connect()
    try:
        await mirror.query("MATCH (k:Knowledge) WHERE k.id STARTS WITH 'TEST-' DETACH DELETE k")
        items = [
            KnowledgeItem(id="TEST-flood", kind="playbook", title="Close the valve when the river rises",
                          text="When the water level passes the flood mark, close the harbour valve.", department="TESTDEPT",
                          applies_to=["test-flood"], uses=["set_valve_state"]),
            KnowledgeItem(id="TEST-fire", kind="playbook", title="Send an engine to a building fire",
                          text="When smoke is detected in a building, dispatch a fire engine.", department="TESTDEPT",
                          applies_to=["test-fire"], uses=["dispatch_unit"]),
            KnowledgeItem(id="TEST-evacuate", kind="playbook", title="Evacuation routes",
                          text="Keep the bridge clear.", department="TESTDEPT", applies_to=["test-flood"], uses=[]),
        ]
        kb = Neo4jKnowledgeBase(mirror, HashingEmbedder())

        await kb.sync(items)
        assert kb.embedded_last_sync == 3
        await kb.sync(items)
        assert kb.embedded_last_sync == 0  # unchanged items are not embedded again
        await kb.sync([items[0].model_copy(update={"text": "Close the harbour valve at 1.5 m."}), *items[1:]])
        assert kb.embedded_last_sync == 1

        hits = await kb.search("the river water level is rising", incident_type="test-flood", department="TESTDEPT", k=3)
        assert hits[0].id == "TEST-flood"
        # The graph traversal marks the items linked to this incident type, and only those.
        linked = {hit.id for hit in hits if "graph:applies_to" in hit.why}
        assert linked == {"TEST-flood", "TEST-evacuate"}
        no_valve = await kb.search("the river water level is rising", department="TESTDEPT", available_actions={"dispatch_unit"}, k=3)
        assert "TEST-flood" not in [hit.id for hit in no_valve]
    finally:
        await mirror.query("MATCH (k:Knowledge) WHERE k.id STARTS WITH 'TEST-' DETACH DELETE k")
        await mirror.query("MATCH (n) WHERE (n:IncidentType AND n.name STARTS WITH 'test-') OR (n:Department AND n.id = 'TESTDEPT') DETACH DELETE n")
        await mirror.close()


@needs_neo4j
async def test_a_scenario_leaves_its_whole_provenance_chain_in_neo4j():
    run_id = f"test-b2-{os.getpid()}"
    models = ModelsConfig()  # the default embedder, so a development database keeps its embeddings

    async with open_backends(GRAPH, models, run_id) as backends:
        assert backends.kb is not None, backends.note
        result = await run_scenario(load_scenario("d3"), inproc_partners(), models=models, speed=0, timeout_s=30,
                                    store=backends.store, kb=backends.kb)
        mirror = backends.store.mirror
        await mirror.flush()
        try:
            assert result.passed, [c.name for c in result.checks if not c.passed]
            assert mirror.errors == 0

            chain = await mirror.query(
                """MATCH (r:Reading)-[:EVIDENCE_FOR]->(i:Incident {run_id: $run})-[:HANDLED_BY]->(d:Decision)-[:ISSUED]->(a:Action)
                   MATCH (r)-[:VERIFIED_BY]->(v:Verdict), (d)-[:CITES]->(v)
                   RETURN i.status AS status, d.tier AS tier, a.status AS result, v.status AS verdict ORDER BY d.id""",
                run=run_id,
            )
            assert [(row["tier"], row["result"]) for row in chain] == [
                ("reflex", "dispatched"), ("deliberate", "dispatched"), ("deliberate", "dispatched"), ("deliberate", "broadcast"),
            ]
            assert {row["status"] for row in chain} == {"closed"} and {row["verdict"] for row in chain} == {"trusted"}

            cited = await mirror.query(
                "MATCH (d:Decision {run_id: $run, tier: 'deliberate'})-[:CITES]->(k:Knowledge) RETURN collect(DISTINCT k.id) AS ids",
                run=run_id,
            )
            assert {"POL-PB-002", "POL-PB-006"} <= set(cited[0]["ids"])

            trail = await mirror.query(
                """MATCH (e:Entity {uid: $uid})-[p:PRESENT_AT]->(z:Zone)
                   RETURN z.id AS zone ORDER BY p.valid_at""",
                uid=f"{run_id}:cit-88213",
            )
            assert [row["zone"] for row in trail] == ["zone-07", "zone-07", "zone-08", "zone-08"]
        finally:
            await mirror.query("MATCH (n {run_id: $run}) DETACH DELETE n", run=run_id)


@needs_neo4j
async def test_every_cited_id_of_a_decision_resolves_in_neo4j():
    run_id = f"test-cited-{os.getpid()}"
    models = ModelsConfig()

    async with open_backends(GRAPH, models, run_id) as backends:
        assert backends.kb is not None, backends.note
        result = await run_scenario(load_scenario("d3"), inproc_partners(), models=models, speed=0, timeout_s=30,
                                    store=backends.store, kb=backends.kb)
        mirror = backends.store.mirror
        await mirror.flush()
        try:
            assert result.passed and mirror.errors == 0
            decisions = sorted(i for kind, i in backends.store.g.nodes if kind == "decision")
            assert decisions
            for decision_id in decisions:
                chain = backends.store.provenance(decision_id)
                assert chain["readings"] and chain["verdicts"], decision_id
                for label, ids in (("Reading", chain["readings"]), ("Verdict", chain["verdicts"]), ("Decision", [decision_id])):
                    found = await mirror.query(f"MATCH (n:{label}) WHERE n.uid IN $uids RETURN n.uid AS uid",
                                               uids=[mirror.uid(i) for i in ids])
                    assert {row["uid"] for row in found} == {mirror.uid(i) for i in ids}, (decision_id, label)
                found = await mirror.query("MATCH (k:Knowledge) WHERE k.id IN $ids RETURN k.id AS id", ids=chain["knowledge"])
                assert {row["id"] for row in found} == set(chain["knowledge"]), (decision_id, "Knowledge")
        finally:
            await mirror.query("MATCH (n {run_id: $run}) DETACH DELETE n", run=run_id)
