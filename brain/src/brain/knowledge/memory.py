"""In-process knowledge base: the same retrieval as the Neo4j one, with no database."""

from __future__ import annotations

import math

from brain.config import KnowledgeConfig
from brain.knowledge import KnowledgeHit, KnowledgeItem, RetrievalTrace, fuse_traced, graph_seeds
from brain.knowledge.embedding import Embedder, cosine, tokens
from brain.knowledge.graph import build_graph, expand


class MemoryKnowledgeBase:
    def __init__(self, embedder: Embedder, options: KnowledgeConfig | None = None) -> None:
        self.embedder = embedder
        self.options = options or KnowledgeConfig()
        self.items: dict[str, KnowledgeItem] = {}
        self._vectors: dict[str, list[float]] = {}
        self._terms: dict[str, list[str]] = {}
        self._graph = build_graph([])

    async def sync(self, items: list[KnowledgeItem]) -> None:
        vectors = self.embedder.embed([item.content for item in items]) if items else []
        for item, vector in zip(items, vectors):
            self.items[item.id] = item
            self._vectors[item.id] = vector
            self._terms[item.id] = tokens(item.content)
        self._graph = build_graph(list(self.items.values()))

    def has(self, item_id: str) -> bool:
        return item_id in self.items

    def title(self, item_id: str) -> str | None:
        return self.items[item_id].title if item_id in self.items else None

    def _keyword_ranking(self, query: str, limit: int) -> list[tuple[str, float]]:
        """BM25 over the item texts: (id, score), best first."""
        wanted = set(tokens(query))
        count = len(self._terms) or 1
        average = sum(len(t) for t in self._terms.values()) / count
        scored = []
        for item_id, terms in self._terms.items():
            score = 0.0
            for term in wanted:
                frequency = terms.count(term)
                if not frequency:
                    continue
                containing = sum(1 for other in self._terms.values() if term in other)
                idf = math.log(1 + (count - containing + 0.5) / (containing + 0.5))
                score += idf * frequency * 2.2 / (frequency + 1.2 * (0.25 + 0.75 * len(terms) / average))
            if score > 0:
                scored.append((score, item_id))
        return [(item_id, score) for score, item_id in sorted(scored, key=lambda pair: (-pair[0], pair[1]))[:limit]]

    def _similarities(self, query_vector: list[float]) -> dict[str, float]:
        return {i: cosine(query_vector, v) for i, v in self._vectors.items()}

    async def search(self, query: str, **filters: object) -> list[KnowledgeHit]:
        return (await self.search_traced(query, **filters))[0]  # type: ignore[arg-type]

    async def search_traced(
        self,
        query: str,
        *,
        incident_type: str | None = None,
        department: str | None = None,
        available_actions: set[str] | None = None,
        kinds: set[str] | None = None,
        k: int = 5,
        graphrag: bool | None = None,
    ) -> tuple[list[KnowledgeHit], RetrievalTrace]:
        if not self.items:
            return [], RetrievalTrace(query=query)
        query_vector = self.embedder.embed([query])[0]
        similar = self._similarities(query_vector)
        by_similarity = sorted(similar, key=lambda i: (-similar[i], i))
        keyword = self._keyword_ranking(query, len(self.items))
        seeds = graph_seeds(self.items, by_similarity, [i for i, _ in keyword], department=department, kinds=kinds, n=self.options.seeds) \
            if (self.options.graphrag == "local" if graphrag is None else graphrag) else None
        expansions = expand(self._graph, sorted(seeds), self.options.hops) if seeds is not None else None
        return fuse_traced(
            self.items, by_similarity, [i for i, _ in keyword],
            incident_type=incident_type, department=department, available_actions=available_actions, kinds=kinds, k=k,
            query=query, scores={"vector": similar, "keyword": dict(keyword)},
            mmr=self.options.mmr, utility_weight=self.options.utility_weight,
            similarity=lambda a, b: cosine(self._vectors[a], self._vectors[b]),
            expansions=expansions, seed_scores=seeds, decay=self.options.decay, conflict_penalty=self.options.conflict_penalty,
        )
