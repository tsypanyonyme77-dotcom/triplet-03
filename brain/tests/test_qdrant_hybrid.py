"""Hybrid search inside Qdrant: dense and keyword searches filtered and fused by the server, agreeing with the Brain's own fusion.

These run on Qdrant's embedded mode, which answers the same queries as a server. With `QDRANT_URL` set, the last tests run on a real server.
"""

import os
import uuid

import pytest

from brain.config import KnowledgeConfig
from brain.knowledge.embedding import HashingEmbedder
from brain.knowledge.evaluate import build_knowledge_base, load_questions
from brain.knowledge.qdrant import QdrantKnowledgeBase, document_vector, query_vector, term_index

QUESTIONS = [q for q in load_questions() if q["expect"]]


@pytest.fixture(scope="module")
async def corpus():
    return list((await build_knowledge_base(HashingEmbedder())).items.values())


async def make(corpus, fusion, **kwargs):
    kb = QdrantKnowledgeBase(HashingEmbedder(), KnowledgeConfig(), fusion=fusion, **kwargs)
    await kb.sync(corpus)
    return kb


def filters_for(kb, question):
    department = question.get("department")
    twin = {item[4:] for item in kb.items if item.startswith("CAP-")}
    return dict(department=department, available_actions=twin - set(question.get("twin_lacks", [])) if department else None,
                kinds=set(question["kinds"]) if question.get("kinds") else None)


async def test_server_fusion_and_client_fusion_agree_on_the_top_three_for_the_eval_questions(corpus):
    client, server = await make(corpus, "client"), await make(corpus, "server")
    overlap = []
    for q in QUESTIONS:
        wanted = [h.id for h in await client.search(q["question"], k=3, **filters_for(client, q))]
        got = [h.id for h in await server.search(q["question"], k=3, **filters_for(server, q))]
        overlap.append(len(set(wanted) & set(got)) / max(len(wanted), 1))

    assert sum(overlap) / len(overlap) >= 0.9, f"top-3 overlap {sum(overlap) / len(overlap):.3f} over {len(overlap)} questions"


async def test_the_trace_names_the_signals_that_found_each_hit(corpus):
    server = await make(corpus, "server")

    hits, trace = await server.search_traced("seal the suspect in with a perimeter", department="POLICE", k=5)

    found_by_server = {i for i, _, _ in trace.signals["hybrid"]}
    assert hits and all(hit.id in found_by_server and "hybrid" in hit.why for hit in hits)
    assert [rank for _, rank, _ in trace.signals["hybrid"]] == list(range(1, len(found_by_server) + 1))
    assert trace.signals["vector"] and trace.signals["keyword"]  # kept for the record and for the evaluator


async def test_a_department_filter_is_applied_by_the_server_before_the_cut(corpus):
    server = await make(corpus, "server")

    hits = await server.search("seal the suspect in", department="UTILITIES", k=5)

    assert hits and all(server.items[h.id].department in ("UTILITIES", None) for h in hits)


async def test_an_item_that_needs_an_actuator_the_twin_lacks_is_never_returned(corpus):
    server = await make(corpus, "server")
    needing = next(i for i in server.items.values() if i.uses and i.department)

    hits = await server.search(needing.title, department=needing.department, available_actions=set(), k=10)

    assert needing.id not in {h.id for h in hits} and all(not server.items[h.id].uses for h in hits)


async def test_only_the_asked_kinds_come_back(corpus):
    server = await make(corpus, "server")

    hits = await server.search("what does the dispatch actuator do", kinds={"capability"}, k=5)

    assert hits and {h.kind for h in hits} == {"capability"}


async def test_the_server_mode_uses_its_own_collection_and_leaves_the_client_one_alone(corpus, tmp_path):
    folder = str(tmp_path / "q")
    client = await make(corpus, "client", location=folder)
    client.client.close()
    server = await make(corpus, "server", location=folder)

    assert client.collection != server.collection and server.collection.endswith("_hybrid")
    server.client.close()
    again = await make(corpus, "client", location=folder)
    assert again.embedded == 0  # the client collection was warm and still is


async def test_a_warm_start_in_server_mode_embeds_nothing(corpus, tmp_path):
    folder = str(tmp_path / "q")
    first = await make(corpus, "server", location=folder)
    before = [h.id for h in await first.search("flood valve", k=3)]
    first.client.close()

    second = await make(corpus, "server", location=folder)

    assert first.embedded == len(corpus) and second.embedded == 0
    assert [h.id for h in await second.search("flood valve", k=3)] == before


async def test_a_changed_item_is_found_by_its_new_words(corpus):
    server = await make(corpus, "server")
    edited = corpus[0].model_copy(update={"text": corpus[0].text + " Zyxwvut protocol applies."})
    await server.sync([edited, *corpus[1:]])

    assert (await server.search("zyxwvut", k=1))[0].id == edited.id


def test_a_word_has_the_same_sparse_index_in_every_run():
    assert term_index("perimeter") == term_index("perimeter") and 0 <= term_index("perimeter") < 2**31
    assert term_index("perimeter") != term_index("perimeters")


def test_a_longer_item_weighs_a_repeated_word_less_than_a_short_one():
    short, long = document_vector(["flood"] * 2, 10), document_vector(["flood"] * 2 + ["other"] * 30, 10)

    assert dict(zip(short.indices, short.values))[term_index("flood")] > dict(zip(long.indices, long.values))[term_index("flood")]


def test_the_query_vector_lists_each_word_once():
    vector = query_vector("flood flood valve")

    assert len(vector.indices) == 2 and set(vector.values) == {1.0}


def test_an_unknown_fusion_is_refused():
    with pytest.raises(ValueError):
        QdrantKnowledgeBase(HashingEmbedder(), fusion="both")


needs_server = pytest.mark.skipif("QDRANT_URL" not in os.environ, reason="needs a Qdrant server: QDRANT_URL=http://127.0.0.1:6333")


@needs_server
async def test_the_hybrid_query_runs_on_a_real_server_and_agrees_with_the_embedded_one(corpus):
    name = f"brain_test_{uuid.uuid4().hex[:8]}"
    remote = QdrantKnowledgeBase(HashingEmbedder(), KnowledgeConfig(), url=os.environ["QDRANT_URL"], collection=name, fusion="server")
    try:
        await remote.sync(corpus)
        local = await make(corpus, "server")
        for q in QUESTIONS[:15]:
            assert [h.id for h in await remote.search(q["question"], k=3, **filters_for(remote, q))] == \
                   [h.id for h in await local.search(q["question"], k=3, **filters_for(local, q))]
    finally:
        remote.client.delete_collection(remote.collection)
