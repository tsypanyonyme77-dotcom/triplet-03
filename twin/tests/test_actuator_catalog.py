"""The actuator catalog the City Brain reads, set_barrier_state, and idempotency keys."""
import pytest
from fastapi.testclient import TestClient

from twin.city.two_blocks import TwoBlocksCity
from twin.config import Settings
from twin.main import create_app

KEY = "k"
H = {"X-Api-Key": KEY}


@pytest.fixture(scope="module")
def city_after_hit():
    city = TwoBlocksCity("ped-hit")
    city.step(60.0)
    return city


def _client(city):
    return TestClient(create_app(Settings(brain_api_key=KEY, emit_enabled=False), city))


def _call(action, params, key=None, actuator_id=None):
    ids = {"dispatch_unit": "dispatch-centre-01", "set_barrier_state": "road-barriers-01", "set_pump_state": "drainage-pumps-01",
           "broadcast_alert": "public-alerts-01"}
    body = {"contract_version": "2026-09-17", "actuator_id": actuator_id or ids[action], "action": action, "params": params,
            "requesting_layer": "city_brain", "justification": "test", "trust_ref": "verdict-1"}
    if key:
        body["idempotency_key"] = key
    return body


def test_the_catalog_lists_every_action_with_schemas(city_after_hit):
    acts = {a["action"]: a for a in _client(city_after_hit).get("/actuators").json()["actuators"]}
    assert set(acts) == {"dispatch_unit", "set_barrier_state", "set_pump_state", "broadcast_alert", "quarantine_device",
                         "isolate_sensor", "clear_quarantine"}
    dispatch, barrier = acts["dispatch_unit"], acts["set_barrier_state"]
    assert dispatch["params_schema"]["properties"]["unit_type"]["enum"] == ["police", "ambulance", "fire"]
    assert dispatch["result_schema"]["properties"]["status"]["enum"] == ["dispatched", "duplicate", "rejected"]
    assert barrier["actuator_id"] == "road-barriers-01" and barrier["params_schema"]["required"] == ["state"]


def test_closing_a_road_by_incident_is_idempotent_and_reopens(city_after_hit):
    client = _client(city_after_hit)
    incident = city_after_hit.sim.call_centre.incidents[0]["id"]
    first = client.post("/actuators/call", json=_call("set_barrier_state", {"state": "closed", "incident_id": incident}), headers=H).json()
    again = client.post("/actuators/call", json=_call("set_barrier_state", {"state": "closed", "road_id": "2-1"}), headers=H).json()
    assert first["result"]["status"] == "closed" and first["result"]["barrier_ids"] == ["barrier-1-2"]
    assert again["result"]["status"] == "duplicate"
    assert city_after_hit.sim.closed_edges == {(1, 2), (2, 1)}
    opened = client.post("/actuators/call", json=_call("set_barrier_state", {"state": "open", "road_id": "1-2"}), headers=H).json()
    assert opened["result"]["status"] == "opened" and not city_after_hit.sim.closed_edges
    bad = client.post("/actuators/call", json=_call("set_barrier_state", {"state": "closed", "road_id": "9-9"}), headers=H).json()
    assert bad["result"] == {"status": "rejected", "reason": "unknown_road"} and not city_after_hit.sim.closed_edges


@pytest.mark.parametrize("params", [{"state": "shut", "road_id": "1-2"}, {"state": "closed"},
                                    {"state": "closed", "road_id": "1-2", "incident_id": "inc-0001"}])
def test_malformed_barrier_params_are_422(city_after_hit, params):
    assert _client(city_after_hit).post("/actuators/call", json=_call("set_barrier_state", params), headers=H).status_code == 422


def test_an_idempotency_key_replays_the_first_answer_and_runs_nothing_twice():
    city = TwoBlocksCity("ped-hit")
    city.step(60.0)
    client = _client(city)
    incident = city.sim.call_centre.incidents[0]["id"]
    body = _call("dispatch_unit", {"unit_type": "police", "incident_id": incident}, key="brain-0001")
    first = client.post("/actuators/call", json=body, headers=H).json()
    retry = client.post("/actuators/call", json=body, headers=H).json()
    assert first["result"]["status"] == "dispatched" and retry["replayed"] is True
    assert retry["result"] == first["result"] and retry["received_at"] == first["received_at"]
    assert sum(e["kind"] == "unit_dispatched" for e in city.timeline()) == 1
    other = _call("dispatch_unit", {"unit_type": "ambulance", "incident_id": incident}, key="brain-0001")
    assert client.post("/actuators/call", json=other, headers=H).status_code == 409


def test_the_drainage_pump_starts_is_idempotent_and_shows_in_the_water_level_reading():
    city = TwoBlocksCity("flood")
    city.step(60.0)
    client = _client(city)
    first = client.post("/actuators/call", json=_call("set_pump_state", {"state": "on", "pump_id": "pump-2-3"}), headers=H).json()
    again = client.post("/actuators/call", json=_call("set_pump_state", {"state": "on", "pump_id": "pump-2-3"}), headers=H).json()
    assert first["result"] == {"status": "on", "pump_id": "pump-2-3", "state": "on", "capacity_m3s": 1.2}
    assert again["result"]["status"] == "duplicate"
    unknown = client.post("/actuators/call", json=_call("set_pump_state", {"state": "on", "pump_id": "pump-9"}), headers=H).json()
    assert unknown["result"] == {"status": "rejected", "reason": "unknown_pump"}
    city.step(city.dt)  # the next tick drains at the new rate
    (level,) = [r for r in city.sensor_readings() if r["sensor_id"] == "wl-dip-2-3"]
    assert level["value"]["pump_on"] and level["value"]["flow_rate_m3s"] == 1.5
    kinds = [e["kind"] for e in client.get("/events").json()["events"]]
    assert "pump_started" in kinds and "actuator_duplicate" in kinds


def test_a_public_alert_is_recorded_and_an_unknown_zone_is_refused(city_after_hit):
    client = _client(city_after_hit)
    sent = client.post("/actuators/call", json=_call("broadcast_alert", {"zone_id": "zone-03", "channel": "app",
                                                                          "message": "Flooding on the south street."}), headers=H).json()
    assert sent["result"]["status"] == "broadcast" and sent["result"]["zone_id"] == "zone-03"
    assert city_after_hit.alerts[-1]["message"] == "Flooding on the south street."
    assert "alert_broadcast" in [e["kind"] for e in client.get("/events").json()["events"]]
    unknown = client.post("/actuators/call", json=_call("broadcast_alert", {"zone_id": "zone-99", "channel": "app",
                                                                             "message": "x"}), headers=H).json()
    assert unknown["result"]["status"] == "rejected" and unknown["result"]["reason"] == "unknown_zone"
    for bad in ({"zone_id": "zone-03", "channel": "pigeon", "message": "x"}, {"zone_id": "zone-03", "channel": "app", "message": ""}):
        assert client.post("/actuators/call", json=_call("broadcast_alert", bad), headers=H).status_code == 422


def test_a_dispatch_can_name_its_station_and_a_wrong_station_is_refused():
    city = TwoBlocksCity("ped-hit")
    city.step(60.0)
    client = _client(city)
    incident = city.sim.call_centre.incidents[0]["id"]
    wrong = client.post("/actuators/call", json=_call("dispatch_unit", {"unit_type": "ambulance", "incident_id": incident,
                                                                         "station_id": "police_station"}), headers=H).json()
    assert wrong["result"] == {"status": "rejected", "reason": "unknown_station", "unit_type": "ambulance", "incident_id": incident}
    sent = client.post("/actuators/call", json=_call("dispatch_unit", {"unit_type": "ambulance", "incident_id": incident,
                                                                        "station_id": "hospital"}), headers=H).json()
    assert sent["result"]["status"] == "dispatched" and city.sim.units[sent["result"]["unit_id"]].station_id == "hospital"


@pytest.mark.parametrize("params", [{"state": "on"}, {"state": "fast", "pump_id": "pump-2-3"},
                                    {"state": "on", "pump_id": "pump-2-3", "incident_id": "inc-0001"},
                                    {"state": "on", "pump_id": ""}])
def test_malformed_pump_params_are_422(city_after_hit, params):
    assert _client(city_after_hit).post("/actuators/call", json=_call("set_pump_state", params), headers=H).status_code == 422
