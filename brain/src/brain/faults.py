"""Faults for scenario runs: things that go wrong around the Brain, so the Test Book can show it carries on.

A scenario names a fault in its `faults` section and the runner wraps the real component in one of these. They count operations, not seconds,
so a run at speed 0 and a run at real speed fail at the same point and a repeated run is identical.

- `knowledge: {"fail_after_searches": N}`: the vector index answers N searches and then stops.
- `twin: {"after_readings": N, "fail_attempts": M}`: after N readings the Twin cannot be reached for the next M attempts, counting the failed
  read and every probe of the Brain's own that fails.
- `guardian: {"after_verdicts": N}`: the Guardian gives N verdicts and then stays silent, for the rest of the run.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from brain.config import KnowledgeConfig
from brain.knowledge import KnowledgeHit, RetrievalTrace
from brain.knowledge.embedding import Embedder
from brain.knowledge.memory import MemoryKnowledgeBase
from brain.knowledge.resilient import ResilientKnowledgeBase
from brain.ports import GuardianUnavailable, TwinError


class FailingKnowledgeBase(MemoryKnowledgeBase):
    """A knowledge base whose index stops answering after `fail_after_searches` searches."""

    def __init__(self, embedder: Embedder, options: KnowledgeConfig | None, fail_after_searches: int) -> None:
        super().__init__(embedder, options)
        self.fail_after, self.searches = fail_after_searches, 0

    async def search_traced(self, query: str, **filters: Any) -> tuple[list[KnowledgeHit], RetrievalTrace]:
        self.searches += 1
        if self.searches > self.fail_after:
            raise ConnectionError("the index stopped answering")
        return await super().search_traced(query, **filters)


def failing_knowledge(embedder: Embedder, options: KnowledgeConfig | None, fail_after_searches: int) -> ResilientKnowledgeBase:
    """The Brain's knowledge base as it is deployed (a primary behind a resilient wrapper), with a primary that will stop. The runtime connects `emit`."""
    return ResilientKnowledgeBase(FailingKnowledgeBase(embedder, options, fail_after_searches), MemoryKnowledgeBase(embedder, options), backend="qdrant")


class FlakyTwin:
    """Passes everything to a real Twin adapter, except that the Twin goes away for a while after `after_readings` readings."""

    def __init__(self, inner: Any, after_readings: int, fail_attempts: int) -> None:
        self._inner, self._after, self._down = inner, after_readings, 0
        self._attempts, self._readings = fail_attempts, 0

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def _try(self) -> None:
        if self._down > 0:
            self._down -= 1
            raise TwinError("the Twin cannot be reached")

    async def get_topology(self) -> dict[str, Any]:
        self._try()
        return await self._inner.get_topology()

    async def stream_readings(self) -> AsyncIterator[dict[str, Any]]:
        self._try()
        async for raw in self._inner.stream_readings():
            yield raw
            self._readings += 1
            if self._readings == self._after:
                self._down = self._attempts - 1  # this raise is the first failed attempt
                raise TwinError("the Twin cannot be reached")


class FlakyGuardian:
    """Passes verdicts to a real Guardian adapter until it has given `after_verdicts`, then answers nothing (a verdict or a quarantine check)."""

    def __init__(self, inner: Any, after_verdicts: int) -> None:
        self._inner, self._after, self._given = inner, after_verdicts, 0

    def _check(self) -> None:
        if self._given >= self._after:
            raise GuardianUnavailable("guardian is down (scripted)")

    async def get_verdict(self, reading: dict[str, Any], deadline_s: float) -> Any:
        self._check()
        verdict = await self._inner.get_verdict(reading, deadline_s)
        self._given += 1
        return verdict

    async def is_quarantined(self, device_id: str) -> bool:
        self._check()
        return await self._inner.is_quarantined(device_id)
