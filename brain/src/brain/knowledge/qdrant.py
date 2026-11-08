"""The knowledge base with Qdrant as its vector index.

Qdrant holds each item's vector, keyed by the item's content hash. It runs embedded (a folder on disk, no server) or against a server
(`graph.qdrant_url`). Two things follow. A warm start embeds nothing: an item whose hash is already stored reuses its stored vector, so only
new or edited items cost an embedding (the in-memory backend embeds the whole corpus every time). And the search can run in two ways:

- **client** (the default): Qdrant answers the dense similarity; keyword search, the fusion, the filters and the trace are the in-memory
  backend's own, so the same query returns the same ids and the same trace.
- **server**: one hybrid query. Each item also carries a sparse keyword vector (BM25 weights, with Qdrant applying the inverse document
  frequency), the dense and keyword searches both run with the filter inside Qdrant, and Qdrant fuses them by reciprocal rank. The Brain
  then adds only what the server cannot know (the link to an incident type, the walk along the playbooks). The trace names one signal,
  `hybrid`, because the server does not say which branch found an item; the dense and keyword rankings are still computed here for the
  record and for the evaluator, and do not decide the order.

The server mode keeps its points in a second collection (`<name>_hybrid`) so the client mode's collection, and a warm start from it, never change.
"""

from __future__ import annotations

import uuid
import zlib
from collections import Counter

from qdrant_client import QdrantClient, models

from brain.config import KnowledgeConfig
from brain.knowledge import KnowledgeHit, KnowledgeItem, RetrievalTrace, fuse_traced, graph_seeds
from brain.knowledge.embedding import Embedder, cosine
from brain.knowledge.graph import build_graph, expand
from brain.knowledge.memory import MemoryKnowledgeBase, tokens

NAMESPACE = uuid.UUID("5d4b2c3a-0000-4000-8000-0000000b7a11")
DENSE, KEYWORD = "dense", "keyword"


def point_id(item_id: str) -> str:
    return str(uuid.uuid5(NAMESPACE, item_id))


def term_index(term: str) -> int:
    """A stable number for a word, the same on every machine and in every run (Python's own `hash` changes between runs)."""
    return zlib.crc32(term.encode()) & 0x7FFFFFFF


def document_vector(terms: list[str], average_length: float) -> models.SparseVector:
    """The BM25 weight of each word in one item. Qdrant multiplies by the word's inverse document frequency (`Modifier.IDF`) at query time."""
    weights: dict[int, float] = {}
    for term, frequency in Counter(terms).items():
        weights[term_index(term)] = frequency * 2.2 / (frequency + 1.2 * (0.25 + 0.75 * len(terms) / (average_length or 1.0)))
    return models.SparseVector(indices=list(weights), values=list(weights.values()))


def query_vector(query: str) -> models.SparseVector:
    indices = sorted({term_index(term) for term in tokens(query)})
    return models.SparseVector(indices=indices, values=[1.0] * len(indices))


class QdrantKnowledgeBase(MemoryKnowledgeBase):
    def __init__(self, embedder: Embedder, options: KnowledgeConfig | None = None, *, location: str = ":memory:", url: str | None = None,
                 collection: str = "brain_kb", api_key: str | None = None, fusion: str = "client") -> None:
        super().__init__(embedder, options)
        if fusion not in ("client", "server"):
            raise ValueError(f"fusion is 'client' or 'server', not {fusion!r}")
        self.fusion = fusion
        self.collection = collection if fusion == "client" else f"{collection}_hybrid"
        self.client = QdrantClient(url=url, api_key=api_key) if url else QdrantClient(location=location) if location == ":memory:" else QdrantClient(path=location)
        self.embedded = 0  # how many items this process had to embed: zero on a warm start

    def _ensure(self, size: int) -> None:
        if self.client.collection_exists(self.collection):
            return
        if self.fusion == "server":
            self.client.create_collection(
                self.collection, vectors_config={DENSE: models.VectorParams(size=size, distance=models.Distance.COSINE)},
                sparse_vectors_config={KEYWORD: models.SparseVectorParams(modifier=models.Modifier.IDF)})
        else:
            self.client.create_collection(self.collection, vectors_config=models.VectorParams(size=size, distance=models.Distance.COSINE))

    def _stored(self, items: list[KnowledgeItem]) -> dict[str, tuple[str, list[float]]]:
        """point id -> (content hash, dense vector) for the items Qdrant already holds."""
        stored: dict[str, tuple[str, list[float]]] = {}
        if self.client.collection_exists(self.collection):
            for point in self.client.retrieve(self.collection, ids=[point_id(i.id) for i in items], with_vectors=True, with_payload=True):
                vector = point.vector[DENSE] if isinstance(point.vector, dict) else point.vector
                stored[str(point.id)] = (point.payload.get("content_hash", ""), vector)
        return stored

    async def sync(self, items: list[KnowledgeItem]) -> None:
        if not items:
            return
        stored = self._stored(items)
        fresh = [i for i in items if stored.get(point_id(i.id), ("", None))[0] != i.content_hash]
        new_vectors = dict(zip((i.id for i in fresh), self.embedder.embed([i.content for i in fresh]))) if fresh else {}
        self.embedded += len(fresh)
        for item in items:
            self.items[item.id] = item
            self._vectors[item.id] = new_vectors.get(item.id) or stored[point_id(item.id)][1]
            self._terms[item.id] = tokens(item.content)
        if self.fusion == "server":
            self._upsert_hybrid(items)
        elif new_vectors:
            self._ensure(len(next(iter(new_vectors.values()))))
            self.client.upsert(self.collection, points=[models.PointStruct(id=point_id(i.id), vector=new_vectors[i.id], payload=self._payload(i)) for i in fresh])
        self._graph = build_graph(list(self.items.values()))

    @staticmethod
    def _payload(item: KnowledgeItem) -> dict[str, object]:
        return {"id": item.id, "kind": item.kind, "department": item.department, "applies_to": item.applies_to, "uses": item.uses,
                "title": item.title, "content_hash": item.content_hash}

    def _upsert_hybrid(self, items: list[KnowledgeItem]) -> None:
        """Every item is written with both vectors: the keyword weights depend on the average length of all items, so one new item moves them all.
        Only the dense vectors are expensive, and those were reused above."""
        self._ensure(len(self._vectors[items[0].id]))
        average = sum(len(t) for t in self._terms.values()) / (len(self._terms) or 1)
        self.client.upsert(self.collection, points=[
            models.PointStruct(id=point_id(i.id), vector={DENSE: self._vectors[i.id], KEYWORD: document_vector(self._terms[i.id], average)}, payload=self._payload(i))
            for i in items])

    def _similarities(self, query_vector_: list[float]) -> dict[str, float]:
        """Cosine similarity of the query to every item, asked of Qdrant."""
        found = self.client.query_points(self.collection, query=query_vector_, using=DENSE if self.fusion == "server" else None, limit=len(self.items), with_payload=["id"]).points
        return {p.payload["id"]: float(p.score) for p in found if p.payload["id"] in self.items}

    def _filter(self, department: str | None, available_actions: set[str] | None, kinds: set[str] | None) -> models.Filter | None:
        """The same refusals `fuse_traced` makes, stated to the server so it cuts after filtering, not before."""
        must: list[models.Condition] = []
        must_not: list[models.Condition] = []
        if kinds is not None:
            must.append(models.FieldCondition(key="kind", match=models.MatchAny(any=sorted(kinds))))
        if department:
            must.append(models.Filter(should=[models.FieldCondition(key="department", match=models.MatchValue(value=department)),
                                              models.IsNullCondition(is_null=models.PayloadField(key="department"))]))
        if available_actions is not None:
            missing = sorted({a for item in self.items.values() for a in item.uses} - available_actions)
            if missing:
                must_not.append(models.FieldCondition(key="uses", match=models.MatchAny(any=missing)))
        return models.Filter(must=must or None, must_not=must_not or None) if must or must_not else None

    async def search_traced(self, query: str, *, incident_type: str | None = None, department: str | None = None, available_actions: set[str] | None = None,
                            kinds: set[str] | None = None, k: int = 5, graphrag: bool | None = None) -> tuple[list[KnowledgeHit], RetrievalTrace]:
        if self.fusion != "server" or not self.items:
            return await super().search_traced(query, incident_type=incident_type, department=department, available_actions=available_actions,
                                               kinds=kinds, k=k, graphrag=graphrag)
        flt = self._filter(department, available_actions, kinds)
        dense = self.embedder.embed([query])[0]
        found = self.client.query_points(
            self.collection, with_payload=["id"], limit=2 * k, query=models.FusionQuery(fusion=models.Fusion.RRF),  # up to the union of the two branches
            prefetch=[models.Prefetch(query=dense, using=DENSE, limit=k, filter=flt), models.Prefetch(query=query_vector(query), using=KEYWORD, limit=k, filter=flt)],
        ).points
        found = sorted((p for p in found if p.payload["id"] in self.items), key=lambda p: (-round(float(p.score), 6), p.payload["id"]))  # ties by id, as the client path breaks them
        fused = [p.payload["id"] for p in found]
        # The signals recorded here do not decide the order; the evaluator reads them, and a person reading the trace can compare them with the server's.
        similar = self._similarities(dense)
        by_similarity = sorted(similar, key=lambda i: (-similar[i], i))
        keyword = self._keyword_ranking(query, len(self.items))
        seeds = graph_seeds(self.items, by_similarity, [i for i, _ in keyword], department=department, kinds=kinds, n=self.options.seeds) \
            if (self.options.graphrag == "local" if graphrag is None else graphrag) else None
        expansions = expand(self._graph, sorted(seeds), self.options.hops) if seeds is not None else None
        hits, trace = fuse_traced(
            self.items, [], [], ranked={"hybrid": fused}, incident_type=incident_type, department=department, available_actions=available_actions,
            kinds=kinds, k=k, query=query, scores={"hybrid": {p.payload["id"]: float(p.score) for p in found}},
            mmr=self.options.mmr, utility_weight=self.options.utility_weight,
            similarity=lambda a, b: cosine(self._vectors[a], self._vectors[b]),
            expansions=expansions, seed_scores=seeds, decay=self.options.decay, conflict_penalty=self.options.conflict_penalty,
        )
        allowed = {i for i in self.items if self._allowed(self.items[i], department, available_actions, kinds)}
        trace.signals["vector"] = [(i, r, round(similar[i], 5)) for r, i in enumerate([i for i in by_similarity if i in allowed][:k], 1)]
        trace.signals["keyword"] = [(i, r, round(dict(keyword)[i], 5)) for r, i in enumerate([i for i, _ in keyword if i in allowed][:k], 1)]
        return hits, trace

    @staticmethod
    def _allowed(item: KnowledgeItem, department: str | None, available_actions: set[str] | None, kinds: set[str] | None) -> bool:
        return ((kinds is None or item.kind in kinds) and not (department and item.department not in (None, department))
                and not (available_actions is not None and any(a not in available_actions for a in item.uses)))

