"""Which zones matter most: graph measures computed on the city, ready to be written back to the graph database.

For each zone: how many shortest paths run through it (betweenness), whether losing it splits the city (articulation point), and what goes dark
if it loses power (the cascade weight, from `engines/cascade.py`). `write_back` sets the three as properties on the Neo4j `:Zone` nodes in one
batch, so a demo query can ask for the five zones to protect first.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import networkx as nx

from brain.engines.cascade import load_dependencies, n_minus_1


@dataclass(frozen=True)
class Criticality:
    betweenness: float
    is_articulation: bool
    n_minus_1_weight: float


def criticality(store: Any, deps: dict[str, list[str]] | None = None) -> dict[str, Criticality]:
    graph = store.zones
    betweenness = nx.betweenness_centrality(graph)
    cut = set(nx.articulation_points(graph))
    deps = load_dependencies(store) if deps is None else deps
    weight = {zone: impact.weight for zone, impact in n_minus_1(store, deps)}
    return {zone: Criticality(round(betweenness[zone], 4), zone in cut, weight.get(zone, 0.0)) for zone in sorted(graph.nodes)}


def write_back_query(results: dict[str, Criticality]) -> tuple[str, dict[str, Any]]:
    """One parameterised Cypher statement for the whole batch (idempotent: it sets, never adds)."""
    rows = [{"id": zone, "criticality": c.betweenness, "articulation": c.is_articulation, "n1_weight": c.n_minus_1_weight} for zone, c in results.items()]
    return ("UNWIND $rows AS row MATCH (z:Zone {id: row.id}) SET z.criticality = row.criticality, z.articulation = row.articulation, z.n1_weight = row.n1_weight", {"rows": rows})
