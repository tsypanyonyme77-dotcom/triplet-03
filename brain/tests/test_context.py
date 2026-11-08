"""The city around an incident, as one small graph: where it is, what is near, who is out, what is watching. No person's identity in it."""

import json

import httpx
import pytest

from brain.api import Hub, create_app
from brain.config import ModelsConfig, PartnersConfig, Policy
from brain.knowledge.context import city_context

HASHING = ModelsConfig.model_validate({"embeddings": {"provider": "hashing"}})


def ids(context, kind):
    return {n.id.split(":", 1)[1] for n in context.nodes if n.kind == kind}


def test_context_lists_the_zones_within_two_hops_and_the_nearest_facility_of_each_kind(world):
    incident = world.crime(at_s=10)

    context = city_context(world.store, incident, hops=2)

    near = world.store.zones_within("zone-07", 2)
    assert ids(context, "zone") >= near
    assert {n.data["hops"] for n in context.nodes if n.kind == "zone"} <= {0, 1, 2, 3, 4}
    kinds = {n.data["type"] for n in context.nodes if n.kind == "facility"}
    assert {"police_station", "fire_station", "hospital"} <= kinds  # the nearest of each kind is there even when farther than two hops
    nearest = [e for e in context.edges if e.rel == "NEAREST"]
    assert {e.from_id for e in nearest} == {"incident:inc-0001"} and len(nearest) == len(kinds)
    assert world.store.nearest_facility("zone-07", "police_station")["id"] in {e.to_id.split(":", 1)[1] for e in nearest}


def test_every_edge_joins_two_nodes_that_are_in_the_context(world):
    incident = world.crime(at_s=10)
    world.store.commit_unit("police-dispatch-05", "unit-p-01", incident_id="inc-0001", mode="respond", zone_id="zone-07")

    context = city_context(world.store, incident, hops=2)

    nodes = {n.id for n in context.nodes}
    assert context.edges and all(e.from_id in nodes and e.to_id in nodes for e in context.edges)
    assert {e.rel for e in context.edges} >= {"ADJACENT_TO", "LOCATED_IN", "MONITORS", "NEAREST", "ASSIGNED_TO"}
    assert len({(e.from_id, e.rel, e.to_id) for e in context.edges}) == len(context.edges)  # no edge twice


def test_context_contains_no_citizen_identity(world):
    incident = world.crime(at_s=10)
    world.sighting("cit-2", "zone-07", at_s=9)
    world.store.commit_unit("police-dispatch-05", "unit-p-01", incident_id="inc-0001", mode="pursuit", zone_id="zone-07", target_id="cit-2", key="k")

    text = city_context(world.store, incident, hops=2).model_dump_json()

    assert "cit-2" not in text and "target" not in text and '"key"' not in text


def test_context_for_a_zone_with_no_facility_says_so(world):
    incident = world.crime(at_s=10)

    context = city_context(world.store, incident, hops=0)

    here = next(n for n in context.nodes if n.id == "zone:zone-07")
    assert here.data["hops"] == 0
    farther = [n for n in context.nodes if n.kind == "zone" and n is not here]
    facility_zones = {n.data["zone_id"] for n in context.nodes if n.kind == "facility"}
    assert all(n.data["hops"] > 0 and n.id.split(":", 1)[1] in facility_zones for n in farther)  # only where a nearest facility is
    assert any("no police_station within 0 hops" in note and "nearest" in note for note in context.notes)


def test_other_open_incidents_and_the_latest_verdict_of_each_sensor_are_part_of_it(world):
    incident = world.crime(at_s=10)
    world.sighting("cit-9", "zone-08", at_s=11, status="suspicious")
    other = incident.model_copy(update={"incident_id": "inc-0002", "type": "flood", "zone_id": "zone-08"})
    world.store.add_incident(other)

    context = city_context(world.store, incident, hops=2)

    assert ids(context, "incident") == {"inc-0001", "inc-0002"}
    sensor = next(n for n in context.nodes if n.id == "sensor:cit-feed-08")
    assert sensor.data["latest_verdict"] == "suspicious" and sensor.data["zone_id"] == "zone-08"


@pytest.fixture
async def api(tmp_path):
    hub = Hub(PartnersConfig(), Policy(), HASHING, mocks="inproc", log_dir=tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(hub)), base_url="http://brain") as client:
        yield client, hub


async def test_the_api_serves_the_context_of_an_incident(api):
    client, hub = api
    assert (await client.get("/api/incidents/inc-0001/context")).status_code == 404

    await client.post("/api/scenarios/t14/run", params={"speed": 0})
    await hub.wait()

    body = (await client.get("/api/incidents/inc-0001/context", params={"hops": 1})).json()
    assert body["incident_id"] == "inc-0001" and body["hops"] == 1 and body["nodes"] and body["edges"]
    assert "cit-88213" not in json.dumps(body)
    assert (await client.get("/api/incidents/inc-9999/context")).status_code == 404
