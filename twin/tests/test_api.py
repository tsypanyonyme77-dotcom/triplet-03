"""The Twin's HTTP API: signed readings, actuator auth, validation with clear errors, idempotency."""
import asyncio

import pytest
from fastapi.testclient import TestClient

from twin.city.two_blocks import TwoBlocksCity
from twin.config import Settings
from twin.contract import CONTRACT_VERSION
from twin.main import create_app
from twin.signing import verify

KEY = "test-key"
GUARDIAN_KEY = "guardian-key"
HMAC = "test-hmac"
INCIDENT = "inc-0001"


@pytest.fixture
def app():
    city = TwoBlocksCity("ped-hit")
    city.step(60.0)  # the accident has happened and been called in
    app = create_app(Settings(emit_enabled=False, brain_api_key=KEY, guardian_api_key=GUARDIAN_KEY, hmac_key=HMAC), city)
    asyncio.run(app.state.emitter.tick())
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


def call(**over):
    body = {"contract_version": CONTRACT_VERSION, "actuator_id": "dispatch-centre-01", "action": "dispatch_unit",
            "params": {"unit_type": "ambulance", "incident_id": INCIDENT}, "requesting_layer": "city_brain",
            "justification": "test", "trust_ref": "verdict-1"}
    body.update(over)
    return body


def post(client, body, key=KEY):
    return client.post("/actuators/call", json=body, headers={"X-Api-Key": key} if key else {})


def test_health_and_zones(client):
    assert client.get("/health").json()["status"] == "ok"
    assert {"zone-01", "zone-02", "zone-03"} <= {z["zone_id"] for z in client.get("/zones").json()["zones"]}


def test_readings_are_signed_and_sequence_increases_per_sensor(client, app):
    first = {r["sensor_id"]: r for r in client.get("/sensors").json()["readings"]}
    assert {"cam-n2", "cam-n5"} <= set(first) and all(verify(r, HMAC) for r in first.values())
    asyncio.run(app.state.emitter.tick())
    second = {r["sensor_id"]: r for r in client.get("/sensors").json()["readings"]}
    assert second["cam-n2"]["sequence_no"] == first["cam-n2"]["sequence_no"] + 1


def test_list_actuators(client):
    acts = {a["action"]: a for a in client.get("/actuators").json()["actuators"]}
    assert {"dispatch_unit", "set_barrier_state"} <= set(acts)
    assert all("handler" not in a for a in acts.values())


def test_auth_required(client):
    assert post(client, call(), key=None).status_code == 401
    assert post(client, call(), key="wrong").status_code == 401


def test_brain_needs_trust_ref_guardian_does_not(client):
    assert post(client, call(trust_ref=None)).status_code == 403
    assert post(client, call(requesting_layer="guardian", trust_ref=None), key=GUARDIAN_KEY).json()["result"]["status"] == "dispatched"


def test_a_layer_cannot_use_another_layers_key(client):
    assert post(client, call(requesting_layer="guardian", trust_ref=None), key=KEY).status_code == 401
    assert post(client, call(), key=GUARDIAN_KEY).status_code == 401


def _device_call(action, **params):
    return call(actuator_id="device-control-01", action=action, params=params, requesting_layer="guardian", trust_ref=None)


def test_quarantine_stops_a_devices_readings_until_it_is_cleared(client, app):
    quarantine = _device_call("quarantine_device", device_id="cam-n2", reason="stuck values")
    assert post(client, quarantine, key=GUARDIAN_KEY).json()["result"]["status"] == "quarantined"
    assert post(client, quarantine, key=GUARDIAN_KEY).json()["result"]["status"] == "duplicate"
    assert [d["device_id"] for d in client.get("/quarantine").json()["devices"]] == ["cam-n2"]
    sensors = {r["sensor_id"] for r in asyncio.run(app.state.emitter.tick())}
    assert "cam-n5" in sensors and not any(s.startswith("cam-n2") for s in sensors)
    cleared = post(client, _device_call("clear_quarantine", device_id="cam-n2"), key=GUARDIAN_KEY).json()["result"]
    assert cleared["status"] == "cleared"
    assert "cam-n2" in {r["sensor_id"] for r in asyncio.run(app.state.emitter.tick())}


def test_only_the_guardian_may_quarantine_and_unknown_devices_are_rejected(client):
    brain_call = {**_device_call("isolate_sensor", device_id="cam-n2", reason="x"), "requesting_layer": "city_brain", "trust_ref": "v-1"}
    assert post(client, brain_call).status_code == 403
    res = post(client, _device_call("isolate_sensor", device_id="ghost", reason="x"), key=GUARDIAN_KEY).json()["result"]
    assert res == {"status": "rejected", "device_id": "ghost", "reason": "unknown_device"}
    assert post(client, _device_call("isolate_sensor", device_id="cam-n2"), key=GUARDIAN_KEY).status_code == 422


def test_partners_never_read_the_engines_ground_truth(client, app):
    app.state.events.emit("sim_incident", "truth", accident="acc1")
    assert not [e for e in client.get("/events").json()["events"] if e["kind"].startswith("sim_")]
    assert [e for e in app.state.events.recent() if e["kind"] == "sim_incident"]


@pytest.mark.parametrize("over,code", [
    ({"contract_version": "1999-01-01"}, 400),
    ({"action": "launch_missile"}, 400),
    ({"actuator_id": "valve-1"}, 400),
    ({"params": {}}, 422),
    ({"params": {"unit_type": "tank", "incident_id": INCIDENT}}, 422),
    ({"params": {"unit_type": "ambulance"}}, 422),
    ({"requesting_layer": "stranger"}, 422),
    ({"justification": ""}, 422),
])
def test_validation_errors_are_clear(client, over, code):
    resp = post(client, call(**over))
    assert resp.status_code == code and resp.json()["detail"]


def test_dispatch_is_idempotent_per_incident_and_unit_type(client):
    first = post(client, call()).json()["result"]
    assert first["status"] == "dispatched" and first["unit_id"]
    again = post(client, call()).json()["result"]
    assert again["status"] == "duplicate" and again["unit_id"] == first["unit_id"]
    kinds = [e["kind"] for e in client.get("/events").json()["events"]]
    assert "unit_dispatched" in kinds and "actuator_duplicate" in kinds


def test_an_unknown_incident_is_rejected_not_an_error(client):
    res = post(client, call(params={"unit_type": "ambulance", "incident_id": "inc-9999"})).json()["result"]
    assert res["status"] == "rejected" and res["reason"] == "unknown_incident"


def test_the_flood_simulator_floods_a_street_once_and_names_unknown_ones_clearly(client):
    first = client.post("/simulators/flood_street", json={"zone_id": "dip-1-4"})
    assert first.status_code == 200 and first.json()["status"] == "started" and first.json()["street"] == "1-4"
    assert client.post("/simulators/flood_street", json={"zone_id": "dip-1-4"}).json()["status"] == "duplicate"
    assert client.post("/simulators/flood_street", json={"zone_id": "dip-9-9"}).status_code == 404
    assert client.post("/simulators/flood_street", json={}).status_code == 422
    zones = {z["id"]: z for z in client.get("/flood").json()["zones"]}
    assert len(zones) == 7 and zones["dip-1-4"]["drain_blocked"] and zones["dip-1-4"]["street"] == [1, 4]
