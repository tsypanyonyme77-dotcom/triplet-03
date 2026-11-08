"""Open the graph and knowledge backends named in the configuration.

Two stores, two jobs. **Neo4j** keeps the City Graph (zones, readings, verdicts, incidents, decisions, actions and the links that
explain a decision) as a durable, explorable copy of what the Brain holds in memory. **Qdrant** keeps the knowledge vectors the agent
teams search (playbooks, rules, capabilities, past incidents): a vector index built for similarity search. Both are on by default;
Qdrant runs embedded (a folder, no server) unless `graph.qdrant_url` names a server. Neither is on the decision path: if one cannot be
reached the Brain says so and carries on from memory. `memory` turns both off; `qdrant` keeps only Qdrant.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from brain.citygraph import MemoryGraphStore
from brain.config import GraphConfig, ModelsConfig, secret
from brain.knowledge import KnowledgeBase
from brain.knowledge.embedding import make_embedder

LOCAL_NEO4J_PASSWORD = "citybrain-local-pw"


@dataclass
class Backends:
    store: MemoryGraphStore
    kb: KnowledgeBase | None  # None: the service builds the in-memory one
    note: str = ""


def _close(kb: Any) -> None:
    """Release an embedded Qdrant folder, which only one open client may hold; the next run in the same process needs it."""
    client = getattr(getattr(kb, "primary", None), "client", None)
    if client is not None:
        try:
            client.close()
        except Exception:  # noqa: BLE001 - closing is best effort
            pass


def _qdrant(graph: GraphConfig, models: ModelsConfig, embedder: Any, fallback: Any = None) -> tuple[Any, str]:
    """The knowledge base on Qdrant, answering from an in-memory copy when Qdrant is away. (kb, note); None and a note when it cannot even open."""
    from brain.knowledge.memory import MemoryKnowledgeBase
    from brain.knowledge.qdrant import QdrantKnowledgeBase
    from brain.knowledge.resilient import ResilientKnowledgeBase

    try:
        primary = QdrantKnowledgeBase(embedder, models.knowledge, location=graph.qdrant_location, url=graph.qdrant_url,
                                      api_key=os.environ.get(graph.qdrant_api_key_env or ""), fusion=graph.qdrant_fusion)
    except Exception as error:  # an index that cannot open must not stop the Brain  # noqa: BLE001
        return fallback, f"Qdrant is unavailable ({type(error).__name__}: {str(error)[:200]}); running without it"
    return ResilientKnowledgeBase(primary, MemoryKnowledgeBase(embedder, models.knowledge), backend="qdrant"), ""


@asynccontextmanager
async def open_backends(
    graph: GraphConfig, models: ModelsConfig, run_id: str, on_error: Callable[[str], None] | None = None
) -> AsyncIterator[Backends]:
    if graph.backend == "memory":
        yield Backends(MemoryGraphStore(), None)
        return
    if graph.backend == "qdrant":
        embedder, note = make_embedder(models.embeddings.provider, models.embeddings.model)
        kb, problem = _qdrant(graph, models, embedder)
        try:
            yield Backends(MemoryGraphStore(), kb, note or problem)
        finally:
            _close(kb)
        return

    from brain.citygraph.neo4j import MirroredGraphStore, Neo4jMirror
    from brain.knowledge.neo4j import Neo4jKnowledgeBase

    # The local database `make neo4j` starts (docker-compose.yml) uses this password when NEO4J_PASSWORD is unset.
    mirror = Neo4jMirror(graph.uri, graph.user, secret(graph.password_env) or LOCAL_NEO4J_PASSWORD, graph.database, run_id, on_error)
    try:
        await mirror.connect()
    except Exception as error:  # noqa: BLE001 - Neo4j is a mirror; if it cannot open the Brain stays in memory
        await mirror.close()
        problem = f"Neo4j at {graph.uri} is unavailable ({type(error).__name__}: {str(error)[:200]}); running in memory"
        kb = None
        if graph.qdrant_url or graph.qdrant_location:  # the knowledge index does not depend on the graph store
            embedder, note = make_embedder(models.embeddings.provider, models.embeddings.model)
            kb, qdrant_problem = _qdrant(graph, models, embedder)
            problem = " ".join(part for part in (problem, note, qdrant_problem) if part)
        try:
            yield Backends(MemoryGraphStore(), kb, problem)
        finally:
            _close(kb)
        return

    embedder, note = make_embedder(models.embeddings.provider, models.embeddings.model)
    kb: KnowledgeBase = Neo4jKnowledgeBase(mirror, embedder, models.knowledge)  # the fallback when Qdrant is not configured or cannot open
    if graph.qdrant_url or graph.qdrant_location:  # Neo4j keeps the city graph; Qdrant keeps the knowledge vectors
        kb, problem = _qdrant(graph, models, embedder, fallback=kb)
        note = note or problem
    try:
        yield Backends(MirroredGraphStore(mirror), kb, note)
    finally:
        _close(kb)
        await mirror.close()
