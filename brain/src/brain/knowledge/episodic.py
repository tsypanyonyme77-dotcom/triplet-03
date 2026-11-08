"""Similar past stories: what the Brain has met before that looks like this, as context for a team and nothing more.

A story is cut from an episode and keeps only the kind of incident, the kind of place, the readings' types and the *shape* of the
plan (which actions, how many). It has no outcome field at all, so "how did it end" cannot leak into a deliberation, and no name,
unit id or zone id. It is never an input to suspect scoring or the gate: nothing under `gate/`, `departments/` or `mind/` imports this
module, and a test keeps it so.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel

from brain.knowledge.embedding import Embedder, cosine
from brain.mind.episodes import Episode, IncidentRef

NOTE = "a past story: context for the team, never evidence, and no record of how it ended"


class PastStory(BaseModel):
    episode_id: str
    incident_type: str
    zone_kind: str
    plan_shape: list[str]
    similarity: float
    note: str = NOTE


def zone_kind(topology: dict[str, Any] | None, zone_id: str) -> str:
    """The kind of place a zone is, without saying which: a city exit, a zone with a facility, an interior zone."""
    if not topology:
        return "zone"
    if zone_id in topology.get("exits", []):
        return "city exit"
    kinds = sorted({f["type"] for f in topology.get("facilities", []) if f.get("zone_id") == zone_id})
    return f"zone with a {', '.join(kinds)}" if kinds else "interior zone"


def plan_shape(episode: Episode) -> list[str]:
    counts = Counter(f"{a.action}{' ' + a.params['mode'] if a.params.get('mode') else ''}" for plan in episode.plans for a in plan.actions)
    return [f"{name} x{n}" for name, n in sorted(counts.items())]


def story_text(episode: Episode, topology: dict[str, Any] | None = None) -> str:
    shape = plan_shape(episode)
    readings = ", ".join(sorted({r.type for r in episode.readings})) or "none"
    text = (f"{episode.incident.type} incident in a {zone_kind(topology, episode.incident.zone_id)}; readings: {readings}; "
            f"{'plan: ' + ', '.join(shape) if shape else 'no plan'}")
    return text + ("; a pursuit went out" if episode.pursuits else "")


def _question(incident: IncidentRef, topology: dict[str, Any] | None) -> str:
    return f"{incident.type} incident in a {zone_kind(topology, incident.zone_id)}"


def _story(episode: Episode, topology: dict[str, Any] | None, similarity: float) -> PastStory:
    return PastStory(episode_id=episode.episode_id, incident_type=episode.incident.type, zone_kind=zone_kind(topology, episode.incident.zone_id),
                     plan_shape=plan_shape(episode), similarity=round(max(similarity, 0.0), 4))


def similar_episodes(
    incident: IncidentRef, episodes: Sequence[Episode], embedder: Embedder, *, topology: dict[str, Any] | None = None, k: int = 3,
) -> list[PastStory]:
    """The `k` episodes that read most like this incident (ties by id). An episode of the same kind of incident always comes before one of
    another kind, whatever the words say: a smog story is a poor guide to a robbery even if both happened in an interior zone."""
    if not episodes:
        return []
    vectors = embedder.embed([_question(incident, topology), *(story_text(e, topology) for e in episodes)])
    scored = sorted(((cosine(vectors[0], vector), episode) for vector, episode in zip(vectors[1:], episodes)),
                    key=lambda pair: (pair[1].incident.type != incident.type, -pair[0], pair[1].episode_id))
    return [_story(episode, topology, similarity) for similarity, episode in scored[:k]]


class Neo4jEpisodeIndex:
    """The same stories kept in Neo4j: `:Episode` nodes with an embedding, linked to the incident type, found by a vector index. The nodes
    hold the story and nothing else: no readings, no plans, no outcome."""

    def __init__(self, mirror: Any, embedder: Embedder) -> None:
        self.mirror, self.embedder = mirror, embedder

    async def sync(self, episodes: Sequence[Episode], topology: dict[str, Any] | None = None) -> None:
        await self.mirror.query(
            "CREATE VECTOR INDEX episode_embedding IF NOT EXISTS FOR (e:Episode) ON (e.embedding) "
            f"OPTIONS {{indexConfig: {{`vector.dimensions`: {self.embedder.dimensions}, `vector.similarity_function`: 'cosine'}}}}"
        )
        await self.mirror.query("CALL db.awaitIndexes(30)")
        if not episodes:
            return
        vectors = self.embedder.embed([story_text(e, topology) for e in episodes])
        rows = [{"id": e.episode_id, "type": e.incident.type, "kind": zone_kind(topology, e.incident.zone_id), "shape": plan_shape(e),
                 "text": story_text(e, topology), "embedding": v} for e, v in zip(episodes, vectors)]
        await self.mirror.query(
            "UNWIND $rows AS row MERGE (e:Episode {id: row.id}) "
            "SET e.incident_type = row.type, e.zone_kind = row.kind, e.plan_shape = row.shape, e.text = row.text, e.embedding = row.embedding, "
            "    e.embedder = $embedder "
            "WITH e, row OPTIONAL MATCH (e)-[old:OF_TYPE]->() DELETE old "
            "WITH DISTINCT e, row MERGE (t:IncidentType {name: row.type}) MERGE (e)-[:OF_TYPE]->(t)",
            rows=rows, embedder=self.embedder.name,
        )
        await self.mirror.query("CALL db.awaitIndexes(30)")

    async def similar(self, incident: IncidentRef, topology: dict[str, Any] | None = None, *, k: int = 3) -> list[PastStory]:
        vector = self.embedder.embed([_question(incident, topology)])[0]
        total = (await self.mirror.query("MATCH (e:Episode) RETURN count(e) AS n"))[0]["n"]
        rows = await self.mirror.query(  # all of them: the same kind of incident goes first, as in the in-memory search
            "CALL db.index.vector.queryNodes('episode_embedding', $k, $vector) YIELD node, score "
            "RETURN node.id AS id, node.incident_type AS type, node.zone_kind AS kind, node.plan_shape AS shape, score",
            k=max(total, k), vector=vector,
        )
        rows.sort(key=lambda r: (r["type"] != incident.type, -r["score"], r["id"]))
        return [PastStory(episode_id=r["id"], incident_type=r["type"], zone_kind=r["kind"], plan_shape=list(r["shape"] or []),
                          similarity=round(max(2 * r["score"] - 1, 0.0), 4)) for r in rows[:k]]
