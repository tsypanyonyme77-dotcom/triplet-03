"""Knowledge base in Neo4j: items are `:Knowledge` nodes with an embedding, linked to the
incident types they apply to and the actions they use. Retrieval is GraphRAG-style:
the vector and full-text indexes pick seeds, a graph traversal adds linked items."""

from __future__ import annotations

from brain.citygraph.neo4j import Neo4jMirror
from brain.config import KnowledgeConfig
from brain.knowledge import Expansion, KnowledgeHit, KnowledgeItem, PathStep, RetrievalTrace, fuse_traced, graph_seeds
from brain.knowledge.embedding import Embedder, cosine, tokens
from brain.knowledge.graph import GROUPS, LINKS

UPSERT = """
UNWIND $rows AS row
MERGE (k:Knowledge {id: row.id})
SET k.kind = row.kind, k.title = row.title, k.text = row.text, k.department = row.department,
    k.helpful = row.helpful, k.harmful = row.harmful, k.content_hash = row.content_hash,
    k.embedder = $embedder, k.embedding = row.embedding, k.updated_at = datetime()
WITH k, row
OPTIONAL MATCH (k)-[old:APPLIES_TO|USES|BELONGS_TO]->()
DELETE old
WITH DISTINCT k, row
FOREACH (name IN row.applies_to | MERGE (t:IncidentType {name: name}) MERGE (k)-[:APPLIES_TO]->(t))
FOREACH (name IN row.uses | MERGE (a:ActionType {name: name}) MERGE (k)-[:USES]->(a))
FOREACH (code IN CASE WHEN row.department IS NULL THEN [] ELSE [row.department] END |
    MERGE (d:Department {id: code}) MERGE (k)-[:BELONGS_TO]->(d))
"""


class Neo4jKnowledgeBase:
    def __init__(self, mirror: Neo4jMirror, embedder: Embedder, options: KnowledgeConfig | None = None) -> None:
        self.mirror = mirror
        self.embedder = embedder
        self.options = options or KnowledgeConfig()
        self.indexed = 0  # every knowledge node in the database, whoever put it there: the indexes answer for all of them
        self.items: dict[str, KnowledgeItem] = {}
        self.embedded_last_sync = 0

    async def sync(self, items: list[KnowledgeItem]) -> None:
        """Upsert items. Only new or changed ones (or ones embedded by a different model) are re-embedded."""
        current = {
            row["id"]: (row["hash"], row["embedder"])
            for row in await self.mirror.query("MATCH (k:Knowledge) RETURN k.id AS id, k.content_hash AS hash, k.embedder AS embedder")
        }
        stale = [item for item in items if current.get(item.id) != (item.content_hash, self.embedder.name)]
        self.embedded_last_sync = len(stale)
        if stale:
            vectors = self.embedder.embed([item.content for item in stale])
            rows = [
                {**item.model_dump(), "content_hash": item.content_hash, "embedding": vector}
                for item, vector in zip(stale, vectors)
            ]
            await self.mirror.query(UPSERT, rows=rows, embedder=self.embedder.name)
            await self.mirror.query("CALL db.awaitIndexes(30)")
        await self._write_links(items)
        for item in items:
            self.items[item.id] = item
        self.indexed = (await self.mirror.query("MATCH (k:Knowledge) RETURN count(k) AS n"))[0]["n"]

    async def _write_links(self, items: list[KnowledgeItem]) -> None:
        """The links between items, rewritten on every sync: they are small, and a link that was removed from a playbook must go."""
        await self.mirror.query(f"MATCH (k:Knowledge)-[r:{'|'.join(LINKS.values())}]->() WHERE k.id IN $ids DELETE r", ids=[i.id for i in items])
        for field, rel in LINKS.items():
            rows = [{"from": item.id, "to": target} for item in items for target in getattr(item, field)]
            if rows:
                await self.mirror.query(f"UNWIND $rows AS l MATCH (a:Knowledge {{id: l.from}}), (b:Knowledge {{id: l.to}}) MERGE (a)-[:{rel}]->(b)", rows=rows)

    async def _expand(self, seeds: list[str], hops: int) -> list[Expansion]:
        """The same walk as `graph.expand`, done by Neo4j with variable-length paths. A walk that revisits an item is a loop and is
        dropped; each item is kept by its shortest path, ties to the path whose ids sort first, as the in-memory walk does."""
        found: list[tuple[str, int, int, list[str], Expansion]] = []
        for order, (group, (rels, direction)) in enumerate(GROUPS.items()):
            arrow = f"-[:{'|'.join(rels)}*1..{int(hops)}]->" if direction == "out" else f"<-[:{'|'.join(rels)}*1..{int(hops)}]-"
            rows = await self.mirror.query(
                f"UNWIND $seeds AS s MATCH p = (a:Knowledge {{id: s}}){arrow}(b:Knowledge) "
                "RETURN s AS seed, [n IN nodes(p) | n.id] AS ids, [r IN relationships(p) | type(r)] AS rels", seeds=seeds,
            )
            best: dict[tuple[str, str], tuple[tuple[int, list[str], list[str]], list[str], list[str]]] = {}
            for row in rows:
                ids, kinds = row["ids"], row["rels"]
                if len(set(ids)) != len(ids) or ids[-1] not in self.items:
                    continue
                rank = (len(kinds), ids, kinds)
                key = (row["seed"], ids[-1])
                if key not in best or rank < best[key][0]:
                    best[key] = (rank, ids, kinds)
            for (seed, item), (rank, ids, kinds) in best.items():
                steps = [PathStep(from_id=ids[i], rel=kinds[i], to_id=ids[i + 1]) if direction == "out"
                         else PathStep(from_id=ids[i + 1], rel=kinds[i], to_id=ids[i]) for i in range(len(kinds))]
                found.append((seed, order, rank[0], ids, Expansion(seed=seed, item=item, group=group, path=steps)))
        return [e for *_, e in sorted(found, key=lambda t: t[:4])]

    def has(self, item_id: str) -> bool:
        return item_id in self.items

    def title(self, item_id: str) -> str | None:
        return self.items[item_id].title if item_id in self.items else None

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
        everything = max(self.indexed, len(self.items), k)  # ask for the whole index: filters come before the cut
        vector = self.embedder.embed([query])[0]
        by_vector = await self.mirror.query(
            "CALL db.index.vector.queryNodes('knowledge_embedding', $k, $vector) YIELD node, score RETURN node.id AS id, score",
            k=everything, vector=vector,
        )
        terms = sorted(set(tokens(query)))
        by_keyword = await self.mirror.query(
            "CALL db.index.fulltext.queryNodes('knowledge_text', $q) YIELD node, score RETURN node.id AS id, score LIMIT $k",
            q=" OR ".join(terms), k=everything,
        ) if terms else []
        linked = await self.mirror.query(
            "MATCH (k:Knowledge)-[:APPLIES_TO]->(:IncidentType {name: $type}) RETURN k.id AS id", type=incident_type
        ) if incident_type else []
        seeds = expansions = None
        if (self.options.graphrag == "local" if graphrag is None else graphrag):
            seeds = graph_seeds(self.items, [r["id"] for r in by_vector], [r["id"] for r in by_keyword], department=department, kinds=kinds, n=self.options.seeds)
            expansions = await self._expand(sorted(seeds), self.options.hops)
        similarity = None
        if self.options.mmr:
            rows = await self.mirror.query("MATCH (k:Knowledge) WHERE k.id IN $ids RETURN k.id AS id, k.embedding AS embedding", ids=list(self.items))
            vectors = {row["id"]: row["embedding"] for row in rows}
            similarity = lambda a, b: cosine(vectors[a], vectors[b])  # noqa: E731
        return fuse_traced(
            self.items, [row["id"] for row in by_vector], [row["id"] for row in by_keyword],
            incident_type=incident_type, department=department, available_actions=available_actions,
            kinds=kinds, graph_linked=[row["id"] for row in linked], k=k, query=query,
            scores={"vector": {row["id"]: row["score"] for row in by_vector}, "keyword": {row["id"]: row["score"] for row in by_keyword}},
            mmr=self.options.mmr, utility_weight=self.options.utility_weight, similarity=similarity,
            expansions=expansions, seed_scores=seeds, decay=self.options.decay, conflict_penalty=self.options.conflict_penalty,
        )
