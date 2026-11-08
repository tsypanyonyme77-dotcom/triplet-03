"""Qdrant as the vector index: the same answers as the in-memory backend, and a warm start that embeds nothing."""


from brain.config import KnowledgeConfig
from brain.knowledge import load_playbook
from brain.knowledge.embedding import HashingEmbedder
from brain.knowledge.memory import MemoryKnowledgeBase
from brain.knowledge.qdrant import QdrantKnowledgeBase

QUESTIONS = ["how do we seal a suspect in", "what to do when a river rises", "send an ambulance to a collision", "traffic jam signal hold", "power overload disconnect"]


def items():
    return [i for d in ("POLICE", "FIRE", "MEDICAL", "MOBILITY", "DISASTER", "UTILITIES") for i in load_playbook(d)]


async def ids(kb, **filters):
    return [[h.id for h in await kb.search(q, k=3, **filters)] for q in QUESTIONS]


async def test_the_same_query_returns_the_same_ids_as_the_memory_backend():
    memory, qdrant = MemoryKnowledgeBase(HashingEmbedder(), KnowledgeConfig()), QdrantKnowledgeBase(HashingEmbedder(), KnowledgeConfig())
    await memory.sync(items())
    await qdrant.sync(items())

    assert await ids(qdrant) == await ids(memory) and await ids(qdrant, department="POLICE") == await ids(memory, department="POLICE")


async def test_a_department_filter_is_applied_before_the_cut():
    qdrant = QdrantKnowledgeBase(HashingEmbedder(), KnowledgeConfig())
    await qdrant.sync(items())

    hits = await qdrant.search("seal the suspect in", department="UTILITIES", k=3)

    assert all(h.id.startswith("UTL") or qdrant.items[h.id].department in ("UTILITIES", None) for h in hits)


async def test_a_warm_start_embeds_nothing_and_a_changed_item_is_embedded_alone(tmp_path):
    folder = str(tmp_path / "qdrant")
    corpus = items()
    first = QdrantKnowledgeBase(HashingEmbedder(), KnowledgeConfig(), location=folder)
    await first.sync(corpus)
    first.client.close()

    second = QdrantKnowledgeBase(HashingEmbedder(), KnowledgeConfig(), location=folder)
    await second.sync(corpus)
    assert first.embedded == len(corpus) and second.embedded == 0

    edited = [corpus[0].model_copy(update={"text": corpus[0].text + " Updated."}), *corpus[1:]]
    second.client.close()
    third = QdrantKnowledgeBase(HashingEmbedder(), KnowledgeConfig(), location=folder)
    await third.sync(edited)
    assert third.embedded == 1


async def test_syncing_twice_is_idempotent():
    qdrant = QdrantKnowledgeBase(HashingEmbedder(), KnowledgeConfig())
    await qdrant.sync(items())
    before = await ids(qdrant)
    await qdrant.sync(items())

    assert await ids(qdrant) == before and qdrant.embedded == len(items())


async def test_no_payload_carries_a_demographic_field():
    qdrant = QdrantKnowledgeBase(HashingEmbedder(), KnowledgeConfig())
    await qdrant.sync(items())
    payloads = [p.payload for p in qdrant.client.scroll(qdrant.collection, limit=1000, with_payload=True)[0]]

    assert payloads and not any({"age", "wealth", "gender", "ethnicity"} & set(p) for p in payloads)


async def test_a_backend_that_cannot_open_falls_back_to_memory(monkeypatch):
    from brain.backends import open_backends
    from brain.config import GraphConfig, ModelsConfig

    def broken(*a, **k):
        raise RuntimeError("no such index")

    monkeypatch.setattr("brain.knowledge.qdrant.QdrantKnowledgeBase.__init__", broken)
    async with open_backends(GraphConfig(backend="qdrant", qdrant_location=":memory:"), ModelsConfig.model_validate({"embeddings": {"provider": "hashing"}}), "t") as backends:
        assert backends.kb is None and "Qdrant is unavailable" in backends.note


async def test_the_evaluator_reports_the_same_metrics_for_every_backend():
    from brain.knowledge.evaluate import run_evaluation

    memory = await run_evaluation(HashingEmbedder(), split="design", backend="memory")
    qdrant = await run_evaluation(HashingEmbedder(), split="design", backend="qdrant")

    assert memory["splits"] == qdrant["splits"]
