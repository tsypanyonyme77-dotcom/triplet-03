"""A knowledge base that survives its index going away.

Reads go to the primary (Qdrant, Neo4j) with a short timeout. When it fails or hangs, the same question is answered from an in-memory copy
that `sync` keeps in step, the timeline says so once (`brain.degraded`), and when the primary answers again it says that too (`brain.recovered`).
The Brain never decides worse for an index outage; it decides from the same playbook with a different engine.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Any

from brain.knowledge import KnowledgeHit, KnowledgeItem, RetrievalTrace


class ResilientKnowledgeBase:
    def __init__(self, primary: Any, fallback: Any, emit: Callable[..., Any] | None = None, timeout_s: float = 0.3, backend: str = "primary") -> None:
        self.primary, self.fallback, self.emit, self.timeout_s, self.backend = primary, fallback, emit, timeout_s, backend
        self.degraded = False

    def _say(self, type: str, data: dict[str, Any]) -> None:
        if self.emit is not None:
            self.emit(type, None, data)

    async def sync(self, items: list[KnowledgeItem]) -> None:
        await self.fallback.sync(items)  # the copy is always complete
        try:
            await asyncio.wait_for(self.primary.sync(items), self.timeout_s * 20)
        except Exception as error:  # noqa: BLE001 - an index outage switches to the in-memory copy
            self._fail(error)

    def _fail(self, error: Exception) -> None:
        if not self.degraded:
            self.degraded = True
            self._say("brain.degraded", {"component": "knowledge", "backend": self.backend, "reason": f"{type(error).__name__}: {str(error)[:120]}", "answering_from": "the in-memory copy"})

    async def search_traced(self, query: str, **filters: Any) -> tuple[list[KnowledgeHit], RetrievalTrace]:
        try:
            found = await asyncio.wait_for(self.primary.search_traced(query, **filters), self.timeout_s)
        except Exception as error:  # noqa: BLE001 - an index outage switches to the in-memory copy
            self._fail(error)
            return await self.fallback.search_traced(query, **filters)
        if self.degraded:
            self.degraded = False
            self._say("brain.recovered", {"component": "knowledge", "backend": self.backend})
        return found

    async def search(self, query: str, **filters: Any) -> list[KnowledgeHit]:
        return (await self.search_traced(query, **filters))[0]

    def has(self, item_id: str) -> bool:
        return self.fallback.has(item_id)

    def title(self, item_id: str) -> str | None:
        return self.fallback.title(item_id)

    def __getattr__(self, name: str) -> Any:  # everything else (items, options...) is the copy's
        return getattr(self.fallback, name)
