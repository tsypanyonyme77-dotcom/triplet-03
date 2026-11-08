"""The City Brain's carriers: readings by cursor, topology, capabilities, its signed actuator calls over
HTTP and MCP, and the link between its incident ids and ours (brain/INTERFACE.md, brain/docs/TWIN-HANDOVER.md)."""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from mcp import Client

from twin.city.two_blocks import TwoBlocksCity
from twin.config import Settings
from twin.main import create_app
from twin.partners.brain_calls import brain_signature, signature_ok
from twin.partners.reading_log import ReadingLog

SECRET = "brain-test-secret"
# the City Brain's own example call (brain/contracts/examples/actuator_call.dispatch_unit.json), signed with its dev secret
BRAIN_EXAMPLE = {
    "contract_version": "2026-09-17", "actuator_id": "police-dispatch-05", "action": "dispatch_unit",
    "params": {"unit_type": "police", "zone_id": "zone-07", "incident_id": "inc-0001", "mode": "pursuit", "target_id": "cit-88213"},
    "requesting_layer": "city_brain",
    "justification": "Suspect cit-88213 score 0.82: copresence (cit-feed-07#4); flight (cit-feed-07#4). Rule POL-001.",
    "trust_ref": "verdict-000004",
    "provenance": {"signed_by": "city_brain", "hmac": "846249a621e4baeda8fe0a7ea7326d462267811059c22314125e4ace81a37f4e"}}


def _app(scenario="ped-hit", seconds=60.0):
    city = TwoBlocksCity(scenario)
    city.step(seconds)
    app = create_app(Settings(brain_hmac_secret=SECRET, emit_enabled=False, live=False), city)
    return app, TestClient(app), city


def _signed(action, actuator_id, params, *, issued=None, nonce=None, secret=SECRET):
    body = {"contract_version": "2026-09-17", "actuator_id": actuator_id, "action": action, "params": params,
            "requesting_layer": "city_brain", "justification": "test", "trust_ref": "verdict-000001",
            "issued_at": (issued or datetime.now(timezone.utc)).isoformat().replace("+00:00", "Z"),
            "nonce": nonce or uuid.uuid4().hex}
    body["provenance"] = {"signed_by": "city_brain", "hmac": brain_signature(body, secret)}
    return body


def _tick(app, times=1):
    for _ in range(times):
        asyncio.run(app.state.emitter.tick())


def test_the_brains_own_example_call_verifies_and_a_changed_one_does_not():
    assert signature_ok(BRAIN_EXAMPLE, "dev-only-brain-secret")
    assert not signature_ok({**BRAIN_EXAMPLE, "trust_ref": "verdict-000005"}, "dev-only-brain-secret")
    assert not signature_ok(BRAIN_EXAMPLE, "another-secret")


def test_readings_page_by_absolute_cursor_with_a_stream_id():
    app, client, _ = _app()
    _tick(app, 2)
    first = client.get("/readings", params={"cursor": 0, "limit": 5}).json()
    assert len(first["readings"]) == 5 and first["next_cursor"] == 5 and first["stream_id"].startswith("twin-")
    rest = client.get("/readings", params={"cursor": 5, "limit": 1000}).json()
    total = 5 + len(rest["readings"])
    assert rest["next_cursor"] == total == app.state.reading_log.end and rest["stream_id"] == first["stream_id"]
    assert client.get("/readings", params={"cursor": total}).json()["readings"] == []
    seqs = {}
    for r in first["readings"] + rest["readings"]:
        assert r["provenance"]["signed_by"] == "twin" and r["contract_version"] == "2026-09-17"
        assert r["sequence_no"] > seqs.get(r["sensor_id"], 0)
        seqs[r["sensor_id"]] = r["sequence_no"]
    assert client.get("/readings", params={"cursor": -1}).status_code == 422


def test_a_full_log_drops_the_oldest_and_keeps_the_cursor_absolute():
    log = ReadingLog(capacity=3, stream_id="s")
    for n in range(5):
        log.append({"n": n})
    assert log.page(0, 10) == {"readings": [{"n": 2}, {"n": 3}, {"n": 4}], "next_cursor": 5, "stream_id": "s"}
    assert log.page(4, 10)["readings"] == [{"n": 4}] and log.page(9, 10) == {"readings": [], "next_cursor": 9, "stream_id": "s"}
    assert ReadingLog().stream_id != ReadingLog().stream_id


def test_topology_names_zones_exits_stations_and_sensors():
    _, client, _ = _app()
    topo = client.get("/topology").json()
    assert {z["id"] for z in topo["zones"]} == {"zone-01", "zone-02", "zone-03"} and topo["exits"] == ["zone-03"]
    assert ["zone-01", "zone-02"] in topo["adjacency"] and ["zone-01", "zone-03"] in topo["adjacency"]
    stations = {f["type"]: f for f in topo["facilities"] if f["type"] != "drainage_pump"}
    assert {t: f["actuator_id"] for t, f in stations.items()} == {
        "hospital": "dispatch-hospital", "police_station": "dispatch-police-station", "fire_station": "dispatch-fire-station"}
    assert all(f["units"] == 1 and f["zone_id"] == "zone-03" for f in stations.values())
    assert {"id": "unit-amb1", "type": "unit_status", "zone_id": "zone-03"} in topo["sensors"]


def test_capabilities_are_only_what_this_city_can_do():
    _, client, _ = _app()
    assert set(client.get("/capabilities").json()) == {"dispatch_unit", "recall_unit", "broadcast_alert", "set_pump_state", "set_barrier_state"}


def test_a_brain_dispatch_goes_from_its_station_to_our_incident_and_the_unit_reports_the_brains_incident():
    app, client, city = _app()
    body = _signed("dispatch_unit", "dispatch-hospital", {"unit_type": "ambulance", "zone_id": "zone-03", "incident_id": "inc-0042"})
    sent = client.post("/actuators/dispatch_unit", json=body).json()
    assert sent["status"] == "dispatched" and sent["unit_id"] == "amb1" and sent["incident_id"] == "inc-0042"
    assert sent["twin_incident_id"] == "inc-0001" and city.sim.units["amb1"].station_id == "hospital"
    again = _signed("dispatch_unit", "dispatch-hospital", {"unit_type": "ambulance", "zone_id": "zone-03", "incident_id": "inc-0042"})
    assert client.post("/actuators/dispatch_unit", json=again).json()["status"] == "duplicate"
    before = app.state.reading_log.end
    _tick(app, 400)
    statuses = [r["value"] for r in client.get("/readings", params={"cursor": before, "limit": 1000}).json()["readings"]
                if r["type"] == "unit_status"]
    while len(statuses) < 3 and app.state.reading_log.end > before + 1000:   # more than a page: read on
        before += 1000
        statuses += [r["value"] for r in client.get("/readings", params={"cursor": before, "limit": 1000}).json()["readings"]
                     if r["type"] == "unit_status"]
    assert [s["state"] for s in statuses] == ["en_route", "on_scene", "returning"]
    assert {s["incident_id"] for s in statuses} == {"inc-0042"} and {s["twin_incident_id"] for s in statuses} == {"inc-0001"}


def test_a_call_with_a_bad_signature_or_too_old_is_refused():
    _, client, city = _app()
    params = {"unit_type": "ambulance", "zone_id": "zone-03", "incident_id": "inc-0042"}
    forged = _signed("dispatch_unit", "dispatch-hospital", params, secret="not-the-secret")
    assert client.post("/actuators/dispatch_unit", json=forged).status_code == 401
    stale = _signed("dispatch_unit", "dispatch-hospital", params, issued=datetime.now(timezone.utc) - timedelta(minutes=5))
    assert client.post("/actuators/dispatch_unit", json=stale).status_code == 401
    assert city.sim.units["amb1"].status == "idle"


def test_a_resent_call_runs_once_and_other_mistakes_are_named():
    _, client, city = _app()
    body = _signed("dispatch_unit", "dispatch-police-station", {"unit_type": "police", "zone_id": "zone-03", "incident_id": "inc-0001"})
    first = client.post("/actuators/dispatch_unit", json=body).json()
    resent = client.post("/actuators/dispatch_unit", json=body).json()
    assert first["status"] == "dispatched" and resent["replayed"] is True and resent["unit_id"] == first["unit_id"]
    assert sum(e["kind"] == "unit_dispatched" for e in city.timeline()) == 1
    wrong = _signed("dispatch_unit", "dispatch-hospital", {"unit_type": "fire", "zone_id": "zone-03", "incident_id": "inc-0001"})
    assert client.post("/actuators/dispatch_unit", json=wrong).json()["reason"] == "wrong_station_for_unit_type"
    nowhere = _signed("dispatch_unit", "police-dispatch-05", {"unit_type": "police", "zone_id": "zone-03", "incident_id": "inc-0001"})
    assert client.post("/actuators/dispatch_unit", json=nowhere).status_code == 400
    valve = _signed("set_valve_state", "set-valve-state-zone-03", {"state": "closed"})
    assert client.post("/actuators/set_valve_state", json=valve).status_code == 404
    no_trust = {**_signed("broadcast_alert", "broadcast-alert-zone-03", {"zone_id": "zone-03", "channel": "app", "message": "x"})}
    no_trust["trust_ref"] = None
    no_trust["provenance"]["hmac"] = brain_signature(no_trust, SECRET)
    assert client.post("/actuators/broadcast_alert", json=no_trust).status_code == 403


def test_a_quarantined_station_sends_no_unit():
    app, client, _ = _app()
    app.state.actuation.devices.block("dispatch-police-station", "quarantine", "test")
    body = _signed("dispatch_unit", "dispatch-police-station", {"unit_type": "police", "zone_id": "zone-03", "incident_id": "inc-0001"})
    assert client.post("/actuators/dispatch_unit", json=body).json()["reason"] == "station_quarantined"


def test_a_recall_goes_to_the_station_that_sent_the_unit():
    _, client, city = _app()
    sent = client.post("/actuators/dispatch_unit", json=_signed("dispatch_unit", "dispatch-police-station", {
        "unit_type": "police", "zone_id": "zone-03", "incident_id": "inc-0042"})).json()
    back = client.post("/actuators/recall_unit", json=_signed("recall_unit", "dispatch-police-station", {
        "unit_id": sent["unit_id"], "incident_id": "inc-0042"})).json()
    assert back == {"status": "recalled", "unit_id": sent["unit_id"]}
    assert city.sim.units[sent["unit_id"]].status in ("returning", "idle")


def test_an_alert_by_zone_actuator_id():
    _, client, city = _app()
    body = _signed("broadcast_alert", "broadcast-alert-zone-02", {"zone_id": "zone-02", "channel": "siren", "message": "Stay indoors."})
    assert client.post("/actuators/broadcast_alert", json=body).json()["status"] == "broadcast"
    assert city.alerts[-1]["zone_id"] == "zone-02"


def test_the_same_operations_as_mcp_tools():
    app, _, city = _app()
    _tick(app)

    async def session():
        async with Client(app.state.mcp_server) as mcp:
            tools = {t.name for t in (await mcp.list_tools()).tools}
            page = (await mcp.call_tool("list_readings", {"cursor": 0, "limit": 3})).structured_content
            topo = (await mcp.call_tool("get_topology", {})).structured_content
            call = _signed("dispatch_unit", "dispatch-hospital", {"unit_type": "ambulance", "zone_id": "zone-03", "incident_id": "inc-0009"})
            sent = (await mcp.call_tool("dispatch_unit", {"call": call})).structured_content
            forged = await mcp.call_tool("dispatch_unit", {"call": _signed("dispatch_unit", "dispatch-hospital", {}, secret="x")})
            return tools, page, topo, sent, forged

    tools, page, topo, sent, forged = asyncio.run(session())
    assert tools == {"get_topology", "list_readings", "dispatch_unit", "recall_unit", "broadcast_alert", "set_pump_state",
                     "set_barrier_state"}
    assert len(page["readings"]) == 3 and page["next_cursor"] == 3 and page["stream_id"] == app.state.reading_log.stream_id
    assert topo["exits"] == ["zone-03"]
    assert sent["status"] == "dispatched" and sent["incident_id"] == "inc-0009" and city.sim.units["amb1"].status == "dispatched"
    assert forged.is_error and "401" in forged.content[0].text


@pytest.mark.parametrize("host,ok", [("twin:8001", True), ("localhost:8001", True), ("evil.example:80", False)])
def test_mcp_checks_the_host_header(host, ok):
    app, _, _ = _app()
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}}}
    with TestClient(app) as client:
        resp = client.post("/mcp", json=init, headers={"Host": host, "Accept": "application/json, text/event-stream"})
    assert (resp.status_code == 200) is ok, resp.text[:200]
