"""The knowledge base: what the departments know, as retrievable and citable items.

Five kinds of item: playbook procedures (written by the team, later edited by the
Academy), reflex rules, the capabilities the Twin reports, reference chunks cut from the
interface card, and (kept apart from the others) episodes of past incidents. Retrieval is hybrid:
vector and keyword search pick seeds, their rankings are fused, then the graph links
(which incident type an item applies to, which actions it uses) filter and extend them.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from importlib import resources
from typing import Any, Literal, Protocol

import yaml
from pydantic import BaseModel, Field

from brain.departments import Rule


class KnowledgeItem(BaseModel):
    id: str
    kind: Literal["playbook", "rule", "capability", "reference", "episode"]
    title: str
    text: str
    department: str | None = None
    applies_to: list[str] = Field(default_factory=list)  # incident types
    uses: list[str] = Field(default_factory=list)  # actuator actions
    # Links to other items, written by hand in the playbook (see knowledge/graph.py): what each one means.
    requires: list[str] = Field(default_factory=list)
    precedes: list[str] = Field(default_factory=list)
    escalates_to: list[str] = Field(default_factory=list)
    conflicts_with: list[str] = Field(default_factory=list)
    substitutes: list[str] = Field(default_factory=list)
    helpful: int = 0
    harmful: int = 0

    @property
    def content(self) -> str:
        return f"{self.title}. {self.text}"

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()[:16]


class PathStep(BaseModel):
    """One link on the way to a hit, in the direction it is really stored: `from_id` REL `to_id`."""

    from_id: str
    rel: str
    to_id: str


class Expansion(BaseModel):
    """An item reached from a seed by walking links: which seed, which kind of walk, and the links it took."""

    seed: str
    item: str
    group: str  # onward (requires, precedes, escalates_to) | before (what precedes the seed) | stand-in (what substitutes for the seed)
    path: list[PathStep]


class RetrievalTrace(BaseModel):
    """How a search chose: what each signal ranked (id, rank from 1, score), what was set aside and why, and what was kept."""

    query: str = ""
    signals: dict[str, list[tuple[str, int, float]]] = Field(default_factory=dict)
    dropped: list[tuple[str, str]] = Field(default_factory=list)
    fused: list[str] = Field(default_factory=list)


class KnowledgeHit(BaseModel):
    id: str
    kind: str
    title: str
    text: str
    score: float
    why: list[str]  # which signals put it here: vector, keyword, graph
    path: list[PathStep] | None = None  # the links that brought it, when GraphRAG found it rather than the search
    trace: RetrievalTrace | None = Field(default=None, exclude=True)  # shared by every hit of one search; not part of a hit's own data


class KnowledgeBase(Protocol):
    async def sync(self, items: list[KnowledgeItem]) -> None: ...

    async def search(
        self,
        query: str,
        *,
        incident_type: str | None = None,
        department: str | None = None,
        available_actions: set[str] | None = None,
        kinds: set[str] | None = None,
        k: int = 5,
    ) -> list[KnowledgeHit]: ...

    async def search_traced(
        self,
        query: str,
        *,
        incident_type: str | None = None,
        department: str | None = None,
        available_actions: set[str] | None = None,
        kinds: set[str] | None = None,
        k: int = 5,
        graphrag: bool | None = None,  # None: as configured
    ) -> tuple[list[KnowledgeHit], RetrievalTrace]: ...

    def has(self, item_id: str) -> bool: ...

    def title(self, item_id: str) -> str | None: ...


def playbook_exists(department_code: str) -> bool:
    return resources.files("brain.departments").joinpath("playbooks", f"{department_code.lower()}.yaml").is_file()


def load_playbook(department_code: str) -> list[KnowledgeItem]:
    path = resources.files("brain.departments").joinpath("playbooks", f"{department_code.lower()}.yaml")
    document = yaml.safe_load(path.read_text())
    return [
        KnowledgeItem(kind="playbook", department=document["department"], **{**item, "text": " ".join(item["text"].split())})
        for item in document["items"]
    ]


def rules_as_knowledge(department_code: str, rules: list[Rule]) -> list[KnowledgeItem]:
    return [
        KnowledgeItem(
            id=rule.id, kind="rule", title=rule.name, text=rule.description or rule.name, department=department_code,
            applies_to=[v for k, v in rule.when.items() if k == "incident.type"],
            uses=[template.action for template in rule.do],
        )
        for rule in rules
    ]


def capabilities_as_knowledge(descriptions: dict[str, str]) -> list[KnowledgeItem]:
    return [
        KnowledgeItem(id=f"CAP-{action}", kind="capability", title=f"Twin actuator: {action}", text=text or action, uses=[action])
        for action, text in sorted(descriptions.items())
    ]


RRF_K = 60


def fuse(*args: Any, **kwargs: Any) -> list[KnowledgeHit]:
    return fuse_traced(*args, **kwargs)[0]


def fuse_traced(
    items: dict[str, KnowledgeItem],
    vector_ranked: list[str],
    keyword_ranked: list[str],
    *,
    incident_type: str | None,
    department: str | None,
    available_actions: set[str] | None,
    kinds: set[str] | None = None,
    graph_linked: list[str] | None = None,
    k: int,
    query: str = "",
    scores: dict[str, dict[str, float]] | None = None,
    mmr: float = 0.0,
    utility_weight: float = 0.0,
    similarity: Callable[[str, str], float] | None = None,
    expansions: list[Expansion] | None = None,
    seed_scores: dict[str, float] | None = None,
    decay: float = 0.5,
    conflict_penalty: float = 0.0,
    ranked: dict[str, list[str]] | None = None,
) -> tuple[list[KnowledgeHit], RetrievalTrace]:
    """Reciprocal-rank fusion of the two seed rankings, then graph expansion, with a trace of how it chose.

    `ranked` replaces the two rankings with whatever named rankings the caller has: a search server that already fused the signals passes
    its one result as `{"hybrid": ids}`, and the trace and each hit's `why` then name that signal.

    The rankings are whole rankings: items that cannot be used (another department's, another kind, needing an actuator the Twin
    lacks) are removed first and only then are the top `k` of each kept, so a large corpus never crowds the right items out.
    `graph_linked` is the result of the graph traversal (items linked to this incident type) when a graph database ran it;
    otherwise the same links are read from the items. `mmr` and `utility_weight` are off at 0. `expansions` (None: GraphRAG off) are
    the items reached by walking the playbooks' links from the search's seeds: each adds its seed's score times `decay` for every
    step, only if it can be used and the search did not find it already; a conflict between two candidates costs the lower one `conflict_penalty`.
    """
    scores = scores or {}
    seed_scores = seed_scores or {}
    entering: dict[str, float] = {}
    why: dict[str, list[str]] = {}
    trace = RetrievalTrace(query=query)

    def refusal(item: KnowledgeItem) -> str | None:
        if kinds is not None and item.kind not in kinds:
            return f"is a {item.kind}, not a {' or '.join(sorted(kinds))}"
        if department and item.department not in (None, department):
            return f"belongs to {item.department}, not {department}"
        # A procedure that needs an actuator the Twin does not expose cannot be followed.
        missing = sorted(a for a in item.uses if available_actions is not None and a not in available_actions)
        return f"needs {', '.join(missing)}, which the Twin does not report" if missing else None

    dropped: dict[str, str] = {}
    for signal, ranking in (ranked.items() if ranked is not None else (("vector", vector_ranked), ("keyword", keyword_ranked))):
        for item_id in ranking[:k]:
            if item_id in items and (reason := refusal(items[item_id])):
                dropped.setdefault(item_id, reason)
        kept = [i for i in ranking if i in items and refusal(items[i]) is None][:k]
        trace.signals[signal] = [(i, rank, round(scores.get(signal, {}).get(i, 0.0), 5)) for rank, i in enumerate(kept, 1)]
        for rank, item_id in enumerate(kept):
            entering[item_id] = entering.get(item_id, 0.0) + 1.0 / (RRF_K + rank + 1)
            why.setdefault(item_id, []).append(signal)

    found_by_search = set(entering)
    # Graph expansion: items linked to this incident type join even if no seed search found them.
    if incident_type:
        if graph_linked is None:
            graph_linked = [item.id for item in items.values() if incident_type in item.applies_to]
        for item_id in graph_linked:
            if item_id in items and (reason := refusal(items[item_id])) is None:
                entering[item_id] = entering.get(item_id, 0.0) + 0.5 / (RRF_K + 1)
                why.setdefault(item_id, []).append("graph:applies_to")
            elif item_id in items and item_id not in entering:
                dropped.setdefault(item_id, reason or "")

    path_of: dict[str, tuple[float, list[PathStep]]] = {}
    if expansions is not None:
        reached: dict[str, float] = {}
        for expansion in expansions:
            seed = items.get(expansion.seed)
            if seed is not None and refusal(seed) and expansion.group != "stand-in":
                continue  # a procedure that cannot be carried out passes nothing on, except who could stand in for it
            target = items.get(expansion.item)
            if target is None or expansion.item in found_by_search:
                continue  # the walk brings in what the search missed; it does not re-rank what the search found
            if reason := refusal(target):
                dropped.setdefault(expansion.item, reason)
                continue
            gain = seed_scores.get(expansion.seed, 0.0) * decay ** len(expansion.path)
            tag = f"graph:{expansion.path[-1].rel.lower()}"
            if gain > reached.get(expansion.item, 0.0):  # the best way in counts, not every way in
                reached[expansion.item] = gain
                path_of[expansion.item] = (gain, expansion.path)
                why[expansion.item] = [tag, *[w for w in why.get(expansion.item, []) if not w.startswith("graph:") or w == "graph:applies_to"]]
        for item_id, gain in reached.items():
            entering[item_id] = entering.get(item_id, 0.0) + gain
        for item_id in sorted(entering) if conflict_penalty else []:  # two candidates that advise against each other: the weaker gives way
            for other in items[item_id].conflicts_with:
                if other in entering and (entering[item_id], item_id) < (entering[other], other):
                    entering[item_id] *= 1 - conflict_penalty
                    why[item_id].append(f"graph:conflicts_with:{other}")
    if utility_weight:
        for item_id in entering:
            helped, harmed = items[item_id].helpful, items[item_id].harmful
            entering[item_id] *= 1.0 + utility_weight * (helped - harmed) / (helped + harmed + 1)
    ordered = sorted(entering, key=lambda i: (-entering[i], i))
    if mmr and similarity is not None and len(ordered) > 1:
        top = entering[ordered[0]] or 1.0
        chosen, rest = [ordered[0]], ordered[1:]
        while rest:
            best = max(rest, key=lambda i: ((1 - mmr) * entering[i] / top - mmr * max(similarity(i, j) for j in chosen), -ordered.index(i)))
            chosen.append(best)
            rest.remove(best)
        ordered = chosen
    hits = [
        KnowledgeHit(id=i, kind=items[i].kind, title=items[i].title, text=items[i].text, score=round(entering[i], 5), why=why[i], trace=trace,
                     path=path_of[i][1] if i in path_of else None)
        for i in ordered[:k]
    ]
    trace.dropped = sorted(dropped.items())
    trace.fused = [hit.id for hit in hits]
    return hits, trace


def summarise(hits: list[KnowledgeHit]) -> list[dict[str, Any]]:
    return [{"id": hit.id, "title": hit.title, "text": hit.text} for hit in hits]


def graph_seeds(
    items: dict[str, KnowledgeItem], vector_ranked: list[str], keyword_ranked: list[str], *,
    department: str | None, kinds: set[str] | None, n: int,
) -> dict[str, float]:
    """The items the walk starts from, with their search scores: the best `n` of each signal that belong to the right department and
    kind. One that needs an actuator the Twin lacks is still a seed, because what could stand in for it is what the walk is for."""
    def eligible(item_id: str) -> bool:
        item = items.get(item_id)
        return item is not None and (kinds is None or item.kind in kinds) and (not department or item.department in (None, department))

    scores: dict[str, float] = {}
    for ranking in (vector_ranked, keyword_ranked):
        for rank, item_id in enumerate([i for i in ranking if eligible(i)][:n]):
            scores[item_id] = scores.get(item_id, 0.0) + 1.0 / (RRF_K + rank + 1)
    return scores
