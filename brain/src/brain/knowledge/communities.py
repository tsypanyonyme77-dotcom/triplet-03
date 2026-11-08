"""Groups of procedures and what they say together, for questions that are about a whole area rather than one procedure ("what can the
Brain do about flooding, and what is blocked?").

A community is the procedures of one department that belong together: those that share an incident type, or are linked. Its summary is
written by code from the item titles, the actions they call and the gate's own list of which actions need a human approval, so it names
only items that exist and says only what the configuration says. No model writes any of it.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

import networkx as nx
from pydantic import BaseModel

from brain.departments import load_manifest
from brain.knowledge import KnowledgeItem
from brain.knowledge.embedding import Embedder, cosine


class Community(BaseModel):
    id: str
    department: str
    name: str
    incident_types: list[str]
    items: list[str]
    actions: list[str]
    held: dict[str, list[str]]  # action -> the items that use it, for every action the gate holds for a human approval
    summary: str


def _list(words: list[str]) -> str:
    return words[0] if len(words) == 1 else f"{', '.join(words[:-1])} and {words[-1]}"


def communities(graph: nx.MultiDiGraph, items: Iterable[KnowledgeItem], *, impact: dict[str, str]) -> list[Community]:
    by_id = {i.id: i for i in items}
    joined = nx.Graph()
    joined.add_nodes_from(by_id)
    shared: dict[tuple[str | None, str], list[str]] = defaultdict(list)
    for item in by_id.values():
        for incident_type in item.applies_to:
            shared[(item.department, incident_type)].append(item.id)
    for together in shared.values():
        joined.add_edges_from((together[0], other) for other in together[1:])
    for u, v in graph.edges():
        if u[0] == v[0] == "item" and u[1] in by_id and v[1] in by_id and by_id[u[1]].department == by_id[v[1]].department:
            joined.add_edge(u[1], v[1])

    found = []
    for n, component in enumerate(sorted(nx.connected_components(joined), key=lambda c: sorted(c)[0]), 1):
        members = [by_id[i] for i in sorted(component)]
        department = members[0].department or "ANY"
        try:
            name = load_manifest(department.lower()).name
        except Exception:  # a department with no manifest keeps its code as its name  # noqa: BLE001
            name = department
        actions = sorted({a for m in members for a in m.uses})
        held = {a: [m.id for m in members if a in m.uses] for a in actions if impact.get(a) == "high"}
        types = sorted({t for m in members for t in m.applies_to})
        held_sentence = ("Held for a human approval: " + ", ".join(f"{a} ({', '.join(ids)})" for a, ids in held.items())
                         if held else "No procedure here is held for a human approval")
        summary = (f"{name} handles {_list(types)}. {len(members)} procedure{'' if len(members) == 1 else 's'}: "
                   f"{'; '.join(m.title for m in members)}. It calls {_list(actions) if actions else 'no actuator'}. {held_sentence}.")
        found.append(Community(id=f"COM-{department}-{n}", department=department, name=name, incident_types=types, items=[m.id for m in members],
                               actions=actions, held=held, summary=summary))
    return found


def search_global(question: str, groups: list[Community], embedder: Embedder, k: int = 2) -> list[Community]:
    """The `k` communities whose summary reads most like the question (ties by id)."""
    if not groups:
        return []
    vectors = embedder.embed([question, *(g.summary for g in groups)])
    ranked = sorted(zip((cosine(vectors[0], v) for v in vectors[1:]), groups), key=lambda pair: (-pair[0], pair[1].id))
    return [g for _, g in ranked[:k]]
