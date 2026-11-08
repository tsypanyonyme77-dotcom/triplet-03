"""The knowledge graph: procedures, incident types, actions and departments, joined by the links the playbooks state.

Links are written by hand in the playbook files (nothing is extracted by a model), so they are exactly as reliable as the people who
wrote them and every one can be read in the YAML. `A requires B`: B must hold for A to be carried out. `A precedes B`: do A before B.
`A escalates_to B`: if A is not enough, B is next. `A conflicts_with B`: they advise against each other (listed on both sides).
`A substitutes B`: A stands in when B cannot be carried out, for instance because the Twin lacks the actuator B needs.
"""

from __future__ import annotations

import networkx as nx

from brain.knowledge import Expansion, KnowledgeItem, PathStep

# The field on an item, and the relationship it becomes in the graph (and in Neo4j).
LINKS = {
    "requires": "REQUIRES", "precedes": "PRECEDES", "escalates_to": "ESCALATES_TO",
    "conflicts_with": "CONFLICTS_WITH", "substitutes": "SUBSTITUTES",
}


def check_links(items: list[KnowledgeItem]) -> tuple[list[KnowledgeItem], list[str]]:
    """The items with every unusable link removed, and what was wrong. An item with a bad link stays; only the link goes.

    Unusable: a link to an item that does not exist, a link to itself, or a conflict that the other item does not list back.
    """
    known = {item.id: item for item in items}
    problems: list[str] = []
    kept = []
    for item in items:
        fixed: dict[str, list[str]] = {}
        for rel in LINKS:
            good = []
            for target in getattr(item, rel):
                if target == item.id:
                    problems.append(f"{item.id} {rel} itself")
                elif target not in known:
                    problems.append(f"{item.id} {rel} {target}, which is not in the knowledge base")
                elif rel == "conflicts_with" and item.id not in known[target].conflicts_with:
                    problems.append(f"{item.id} conflicts_with {target} but {target} does not list {item.id}: a conflict must be symmetric")
                else:
                    good.append(target)
            fixed[rel] = good
        kept.append(item.model_copy(update=fixed))
    return kept, problems


def build_graph(items: list[KnowledgeItem]) -> nx.MultiDiGraph:
    """Nodes are `(kind, name)`: `item`, `incident_type`, `action` and `department`. Every edge has a `rel`."""
    graph = nx.MultiDiGraph()
    for item in items:
        node = ("item", item.id)
        graph.add_node(node, kind=item.kind, title=item.title)
        for incident_type in item.applies_to:
            graph.add_edge(node, ("incident_type", incident_type), rel="APPLIES_TO")
        for action in item.uses:
            graph.add_edge(node, ("action", action), rel="USES")
        if item.department:
            graph.add_edge(node, ("department", item.department), rel="BELONGS_TO")
        for field, rel in LINKS.items():
            for target in getattr(item, field):
                graph.add_edge(node, ("item", target), rel=rel)
    return graph


# How each kind of walk reads the links. `out` follows the arrow, `in` goes against it.
GROUPS: dict[str, tuple[tuple[str, ...], str]] = {
    "onward": (("REQUIRES", "PRECEDES", "ESCALATES_TO"), "out"),  # what must hold, what comes next, what is next if this is not enough
    "before": (("PRECEDES",), "in"),  # what comes before this
    "stand-in": (("SUBSTITUTES",), "in"),  # what can stand in for this
}


def expand(graph: nx.MultiDiGraph, seeds: list[str], hops: int) -> list[Expansion]:
    """Walk the links from each seed, at most `hops` steps, breadth first, so each item is reached by its shortest path (ties: the path
    whose ids sort first). Never back to the seed, never through a conflict, and a walk stays in one kind (`GROUPS`)."""
    found: list[Expansion] = []
    for seed in sorted(set(seeds)):
        start = ("item", seed)
        if start not in graph:
            continue
        for group, (rels, direction) in GROUPS.items():
            seen = {start}
            frontier: list[tuple[tuple[str, str], list[PathStep]]] = [(start, [])]
            for _ in range(hops):
                following = []
                for current, path in frontier:
                    edges = graph.out_edges(current, data=True) if direction == "out" else graph.in_edges(current, data=True)
                    steps = sorted(((v if direction == "out" else u), data["rel"], u, v) for u, v, data in edges if data["rel"] in rels)
                    for other, rel, u, v in steps:
                        if other[0] != "item" or other in seen:
                            continue
                        seen.add(other)
                        walked = [*path, PathStep(from_id=u[1], rel=rel, to_id=v[1])]
                        following.append((other, walked))
                        found.append(Expansion(seed=seed, item=other[1], group=group, path=walked))
                frontier = following
    return found
