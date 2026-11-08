"""Similar past stories: context for a deliberation, never evidence, never a result."""

import os
import re
from pathlib import Path

from brain.knowledge.embedding import HashingEmbedder
from brain.knowledge.episodic import PastStory, similar_episodes, story_text, zone_kind
from brain.mind.episodes import Episode, EpisodeReading, IncidentRef, PlanAction, PlanRecord, Pursuit
from tests.test_neo4j import URI, needs_neo4j

ROOT = Path(__file__).resolve().parent.parent
TOPOLOGY = {"zones": [{"id": "zone-01", "name": "Harbor"}, {"id": "zone-04", "name": "Market"}, {"id": "zone-07", "name": "Downtown"}],
            "exits": ["zone-01"], "facilities": [{"id": "ps-05", "type": "police_station", "zone_id": "zone-07"}]}


def episode(n, kind, zone, *, actions=(), reading_types=("cctv_anomaly",), outcome="apprehended", pursuit=None) -> Episode:
    return Episode(
        episode_id=f"ep-{n}", incident=IncidentRef(type=kind, zone_id=zone), outcome=outcome, team_runs=1 if actions else 0,
        readings=[EpisodeReading(reading_id=f"s-{i}#1", sensor_id=f"s-{i}", type=t, zone_id=zone, at_ms=i, value={"citizen_id": "p-1"}, verdict="trusted",
                                 verdict_id=f"v-{i}") for i, t in enumerate(reading_types)],
        plans=[PlanRecord(reason="plan", actions=[PlanAction(action=a, params={"zone_id": z, "mode": m} if m else {"zone_id": z}) for a, m, z in actions])] if actions else [],
        pursuits=[Pursuit(zone_id=zone)] if pursuit else [],
    )


STORIES = [
    episode(1, "crime", "zone-07", actions=[("dispatch_unit", "contain", "zone-04"), ("dispatch_unit", "contain", "zone-08"), ("broadcast_alert", None, "zone-07")],
            reading_types=("cctv_anomaly", "citizen_activity"), pursuit=True),
    episode(2, "crime", "zone-07", actions=[("dispatch_unit", "contain", "zone-04"), ("broadcast_alert", None, "zone-07")], reading_types=("cctv_anomaly", "citizen_activity"), outcome="lost"),
    episode(3, "crime", "zone-04", actions=[("broadcast_alert", None, "zone-04")], reading_types=("gunshot",)),
    episode(4, "flood", "zone-01", reading_types=("water_level",), outcome="cleared"),
    episode(5, "flood", "zone-01", reading_types=("water_level", "emergency_call"), outcome="cleared"),
    episode(6, "smog", "zone-04", reading_types=("air_quality",), outcome="cleared"),
    episode(7, "overload", "zone-04", reading_types=("power_load",), outcome="cleared"),
    episode(8, "jam", "zone-04", reading_types=("traffic_camera",), outcome="cleared"),
]


def test_a_past_story_has_no_outcome_and_no_identity():
    story = similar_episodes(IncidentRef(type="crime", zone_id="zone-07"), STORIES, HashingEmbedder(), topology=TOPOLOGY, k=2)[0]

    assert isinstance(story, PastStory) and "outcome" not in PastStory.model_fields
    text = story.model_dump_json() + story_text(STORIES[0], TOPOLOGY)
    for banned in ("apprehended", "lost", "cleared", "citizen_id", "unit-", "target", "zone-07"):
        assert banned not in text, banned
    assert not re.search(r"\bp-\d+\b", text)  # a person renamed inside an episode
    assert re.fullmatch(r"ep-\d+", story.episode_id)


def test_the_text_that_is_embedded_says_the_kind_of_incident_the_kind_of_place_and_the_shape_of_the_plan():
    assert zone_kind(TOPOLOGY, "zone-01") == "city exit" and zone_kind(TOPOLOGY, "zone-07") == "zone with a police_station"
    assert zone_kind(TOPOLOGY, "zone-04") == "interior zone" and zone_kind(None, "zone-04") == "zone"

    assert story_text(STORIES[0], TOPOLOGY) == (
        "crime incident in a zone with a police_station; readings: cctv_anomaly, citizen_activity; "
        "plan: broadcast_alert x1, dispatch_unit contain x2; a pursuit went out")
    assert story_text(STORIES[3], TOPOLOGY) == "flood incident in a city exit; readings: water_level; no plan"


def test_a_leave_one_out_search_finds_a_story_of_the_same_incident_type():
    embedder, hits = HashingEmbedder(), 0
    for held_out in STORIES:
        rest = [e for e in STORIES if e.episode_id != held_out.episode_id]
        if not any(e.incident.type == held_out.incident.type for e in rest):
            continue  # nothing of its kind left to find
        found = similar_episodes(held_out.incident, rest, embedder, topology=TOPOLOGY, k=1)[0]
        hits += next(e for e in rest if e.episode_id == found.episode_id).incident.type == held_out.incident.type
    assert hits == 5  # all five episodes that have a sibling of their own kind


def test_stories_are_labelled_as_context_not_evidence():
    story = similar_episodes(IncidentRef(type="flood", zone_id="zone-01"), STORIES, HashingEmbedder(), topology=TOPOLOGY, k=1)[0]

    assert story.incident_type == "flood" and story.zone_kind == "city exit"
    assert story.note == "a past story: context for the team, never evidence, and no record of how it ended"
    assert 0 < story.similarity <= 1


def test_the_search_is_deterministic_and_respects_k_and_an_empty_history():
    query = IncidentRef(type="crime", zone_id="zone-07")

    first = similar_episodes(query, STORIES, HashingEmbedder(), topology=TOPOLOGY, k=3)

    assert [s.episode_id for s in first] == [s.episode_id for s in similar_episodes(query, list(STORIES), HashingEmbedder(), topology=TOPOLOGY, k=3)]
    assert len(first) == 3 and similar_episodes(query, [], HashingEmbedder(), k=3) == []


def test_nothing_that_decides_an_action_imports_episodic_retrieval():
    for folder in ("src/brain/gate", "src/brain/departments/police", "src/brain/departments/rules", "src/brain/triage", "src/brain/perception",
                   "src/brain/graph", "src/brain/mind"):
        for path in (ROOT / folder).rglob("*.py"):
            assert "episodic" not in path.read_text(), path  # a past story may inform a team's reading, never a score or the gate
    for path in (ROOT / "src/brain/departments").glob("*.py"):
        if path.name != "team.py":  # the agents' read-only tool is the one place it is meant to be used
            assert "episodic" not in path.read_text(), path


@needs_neo4j
async def test_episodes_are_nodes_in_neo4j_and_the_same_story_comes_back():
    from brain.citygraph.neo4j import Neo4jMirror
    from brain.knowledge.episodic import Neo4jEpisodeIndex

    mirror = Neo4jMirror(URI, "neo4j", os.environ["NEO4J_PASSWORD"], "neo4j", "test-episodes")
    await mirror.connect()
    try:
        index = Neo4jEpisodeIndex(mirror, HashingEmbedder())
        await index.sync(STORIES, TOPOLOGY)
        await index.sync(STORIES, TOPOLOGY)  # again: nothing doubled
        count = await mirror.query("MATCH (e:Episode) WHERE e.id STARTS WITH 'ep-' RETURN count(e) AS n")
        assert count[0]["n"] == len(STORIES)
        memory = similar_episodes(IncidentRef(type="flood", zone_id="zone-01"), STORIES, HashingEmbedder(), topology=TOPOLOGY, k=2)
        stored = await index.similar(IncidentRef(type="flood", zone_id="zone-01"), TOPOLOGY, k=2)
        assert [s.episode_id for s in stored] == [s.episode_id for s in memory]
        assert all("outcome" not in row for row in await mirror.query("MATCH (e:Episode) WHERE e.id STARTS WITH 'ep-' RETURN keys(e) AS keys"))
        outcome_keys = await mirror.query("MATCH (e:Episode) WHERE e.id STARTS WITH 'ep-' UNWIND keys(e) AS key RETURN DISTINCT key")
        assert not {"outcome", "readings", "plans"} & {r["key"] for r in outcome_keys}
    finally:
        await mirror.query("MATCH (e:Episode) WHERE e.id STARTS WITH 'ep-' DETACH DELETE e")
        await mirror.close()
