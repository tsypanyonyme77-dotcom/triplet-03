"""The knowledge base outlives its index: answers come from the copy, the outage is reported once, recovery is reported, a hang is cut."""

import asyncio

from brain.config import KnowledgeConfig
from brain.knowledge import load_playbook
from brain.knowledge.embedding import HashingEmbedder
from brain.knowledge.memory import MemoryKnowledgeBase
from brain.knowledge.resilient import ResilientKnowledgeBase

ITEMS = [i for d in ("POLICE", "FIRE", "MEDICAL", "MOBILITY", "DISASTER", "UTILITIES") for i in load_playbook(d)]


class Flaky(MemoryKnowledgeBase):
    mode = "up"  # up | down | hang

    async def search_traced(self, query, **filters):
        if self.mode == "down":
            raise ConnectionError("index unreachable")
        if self.mode == "hang":
            await asyncio.sleep(10)
        return await super().search_traced(query, **filters)


def build(events):
    primary = Flaky(HashingEmbedder(), KnowledgeConfig())
    kb = ResilientKnowledgeBase(primary, MemoryKnowledgeBase(HashingEmbedder(), KnowledgeConfig()), emit=lambda t, s, d: events.append((t, d)), timeout_s=0.2, backend="qdrant")
    return primary, kb


async def ids(kb):
    return [h.id for h in await kb.search("seal the suspect in", k=3)]


async def test_a_failing_primary_is_answered_from_the_fallback_and_reported_once():
    events = []
    primary, kb = build(events)
    await kb.sync(ITEMS)
    primary.mode = "down"

    await ids(kb)
    await ids(kb)

    assert [t for t, _ in events] == ["brain.degraded"] and events[0][1]["backend"] == "qdrant"


async def test_the_fallback_returns_the_same_ids_the_primary_did():
    primary, kb = build([])
    await kb.sync(ITEMS)
    before = await ids(kb)
    primary.mode = "down"

    assert await ids(kb) == before


async def test_recovery_is_reported_when_the_primary_answers_again():
    events = []
    primary, kb = build(events)
    await kb.sync(ITEMS)
    primary.mode = "down"
    await ids(kb)
    primary.mode = "up"
    await ids(kb)

    assert [t for t, _ in events] == ["brain.degraded", "brain.recovered"]


async def test_a_search_that_hangs_is_cut_at_the_timeout():
    primary, kb = build([])
    await kb.sync(ITEMS)
    primary.mode = "hang"
    started = asyncio.get_running_loop().time()

    assert await ids(kb)
    assert asyncio.get_running_loop().time() - started < 1.0


async def test_a_scenario_decides_the_same_with_the_index_down():
    from brain.config import ModelsConfig
    from brain.scenario import inproc_partners, load_scenario, run_scenario

    models = ModelsConfig.model_validate({"embeddings": {"provider": "hashing"}})

    async def decisions(kb):
        result = await run_scenario(load_scenario("t14"), inproc_partners(), models=models, speed=0, timeout_s=30, kb=kb)
        return result.passed, sorted(str(e.data["params"]) for e in result.sink.of("brain.decision.made"))

    primary, down = build([])
    primary.mode = "down"
    healthy = MemoryKnowledgeBase(HashingEmbedder(), KnowledgeConfig())

    assert await decisions(down) == await decisions(healthy)
