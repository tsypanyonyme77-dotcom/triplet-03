"""Graph algorithms and knowledge retrieval, on the sample city."""

from pathlib import Path

import pytest

from brain.config import ScoringPolicy
from brain.departments import load_rules
from brain.knowledge import capabilities_as_knowledge, fuse, load_playbook, rules_as_knowledge
from brain.knowledge.embedding import HashingEmbedder, model_cache_dir
from brain.knowledge.memory import MemoryKnowledgeBase
from brain.tools import geo, graphq


def test_tight_perimeter_is_the_minimum_cut_around_the_suspect(world):
    cut = geo.containment_cut(world.store, "zone-07")

    assert cut["possible"] and cut["zones"] == ["zone-04", "zone-08"]


def test_a_wider_lead_moves_the_perimeter_out_to_the_exits(world):
    cut = geo.containment_cut(world.store, "zone-07", lead_hops=1)

    assert cut["zones"] == ["zone-01", "zone-03", "zone-09"]


@pytest.mark.parametrize("zone", ["zone-07", "zone-08", "zone-05", "zone-04"])
def test_holding_the_cut_really_seals_the_suspect_in(world, zone):
    import networkx as nx

    cut = geo.containment_cut(world.store, zone)
    remaining = world.store.zones.copy()
    remaining.remove_nodes_from(cut["zones"])

    reachable = nx.node_connected_component(remaining, zone)
    assert not reachable & set(world.store.exits)


def test_no_perimeter_once_the_suspect_is_at_an_exit(world):
    cut = geo.containment_cut(world.store, "zone-09")

    assert not cut["possible"] and "exit" in cut["reason"]


def test_escape_prediction_follows_exits_and_heading(world):
    prediction = geo.predict_escape(world.store, "zone-07", heading_zone_id="zone-08")

    assert [z["zone_id"] for z in prediction["next_zones"]] == ["zone-08", "zone-04"]
    assert abs(sum(z["probability"] for z in prediction["next_zones"]) - 1.0) < 0.01
    assert geo.predict_escape(world.store, "zone-09")["at_exit"]


def test_nearest_units_skips_stations_that_are_empty_or_quarantined(world):
    assert [u["station_id"] for u in geo.nearest_units(world.store, "zone-08")] == ["ps-05", "ps-09"]

    world.store.commit_unit("police-dispatch-05")
    world.store.commit_unit("police-dispatch-05")
    world.store.mark_quarantined("police-dispatch-09")

    assert geo.nearest_units(world.store, "zone-08") == []


def test_copresence_says_in_words_when_flight_singles_the_subject_out(world):
    incident = world.crime(at_s=10)
    for citizen in ("cit-1", "cit-2"):
        world.sighting(citizen, "zone-07", at_s=9)
    world.sighting("cit-1", "zone-08", at_s=20, speed=18, activity="running")
    world.sighting("cit-2", "zone-07", at_s=21, speed=4)

    scene = graphq.copresence(world.store, incident, ScoringPolicy(), subject_id="cit-1")

    assert scene["others_who_moved_fast_after"] == 0
    assert scene["conclusion"].startswith("Only the subject left the scene fast")


def test_copresence_tells_one_person_fleeing_from_a_crowd_scattering(world):
    incident = world.crime(at_s=10)
    for citizen in ("cit-1", "cit-2", "cit-3"):
        world.sighting(citizen, "zone-07", at_s=9)
    world.sighting("cit-1", "zone-08", at_s=20, speed=18, activity="running")
    world.sighting("cit-2", "zone-04", at_s=21, speed=16, activity="running")
    world.sighting("cit-3", "zone-07", at_s=22, speed=3)

    scene = graphq.copresence(world.store, incident, ScoringPolicy(), subject_id="cit-1")

    assert scene["subject"]["moved_fast_after"] and scene["subject"]["last_zone_id"] == "zone-08"
    assert [p["entity_id"] for p in scene["others_at_scene"]] == ["cit-2", "cit-3"]  # never the subject
    assert scene["others_who_moved_fast_after"] == 1
    assert scene["conclusion"].startswith("1 other person at the scene also left fast")


@pytest.fixture
async def kb():
    base = MemoryKnowledgeBase(HashingEmbedder())
    await base.sync([
        *load_playbook("POLICE"),
        *rules_as_knowledge("POLICE", load_rules("police.yaml")),
        *capabilities_as_knowledge({"dispatch_unit": "Dispatch a unit.", "broadcast_alert": "Send a public alert."}),
    ])
    return base


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("several people ran away from the scene, is flight good evidence?", "POL-PB-007"),
        ("warn residents near a robbery", "POL-PB-005"),
        ("the suspect has reached a city exit", "POL-PB-009"),
        ("seal the suspect with a tight perimeter", "POL-PB-002"),
    ],
)
async def test_retrieval_finds_the_relevant_procedure(kb, question, expected):
    hits = await kb.search(question, incident_type="crime", department="POLICE", kinds={"playbook"}, k=3)

    assert expected in [hit.id for hit in hits]
    assert hits[0].why


async def test_procedures_needing_an_actuator_the_twin_lacks_are_not_offered(kb):
    hits = await kb.search("warn residents near a robbery", incident_type="crime", available_actions={"dispatch_unit"}, k=12)

    assert "POL-PB-005" not in [hit.id for hit in hits]
    assert all(hit.kind != "capability" or hit.id == "CAP-dispatch_unit" for hit in hits)


async def test_graph_links_bring_in_items_no_search_matched(kb):
    seeded = fuse(kb.items, ["POL-PB-001"], [], incident_type="crime", department="POLICE",
                  available_actions=None, kinds={"playbook"}, k=5)

    assert seeded[0].id == "POL-PB-001" and "vector" in seeded[0].why
    assert len(seeded) == 5 and all(hit.why == ["graph:applies_to"] for hit in seeded[1:])
    assert kb.has("POL-PB-001") and kb.has("POL-001") and not kb.has("POL-PB-999")


def test_the_embedding_model_is_kept_where_a_reboot_does_not_empty_it(monkeypatch, tmp_path):
    monkeypatch.delenv("FASTEMBED_CACHE_PATH", raising=False)
    monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
    assert model_cache_dir() == Path.home() / ".cache" / "city-brain" / "fastembed"

    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
    assert model_cache_dir() == tmp_path / "city-brain" / "fastembed"

    monkeypatch.setenv("FASTEMBED_CACHE_PATH", str(tmp_path / "elsewhere"))
    assert model_cache_dir() == tmp_path / "elsewhere"
