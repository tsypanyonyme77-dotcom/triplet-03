"""A building fire through the Twin: its sensors tell one story, the simulator endpoint starts it, the chain answers it."""
import asyncio
import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import load_mock
from twin.city.two_blocks import TwoBlocksCity
from twin.config import Settings
from twin.main import create_app
from twin.testbook import SCENARIOS

OPERATOR = "op"


def _by_type(readings: list[dict]) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = {}
    for r in readings:
        out.setdefault(r["type"], []).append(r)
    return out


def _burning_city(seconds: float) -> TwoBlocksCity:
    city = TwoBlocksCity("building-fire")
    city.step(seconds)
    return city


def test_smoke_sensor_air_quality_and_cameras_tell_the_same_story():
    city = TwoBlocksCity("building-fire")
    city.step(8.0)
    quiet = _by_type(city.sensor_readings())
    assert "building_fire" not in quiet                         # nothing yet: the sensors send only while they smell smoke
    assert {r["value"]["aqi"] for r in quiet["air_quality"]} == {38}
    assert all(not r["value"]["smoke_detected"] for r in quiet["traffic_camera"])
    city.step(40.0)
    burning = _by_type(city.sensor_readings())
    (smoke,) = burning["building_fire"]
    v = smoke["value"]
    assert smoke["sensor_id"] == "fire-bld-01-03" and smoke["zone_id"] == "zone-01" and smoke["department"] == "fire"
    assert v["smoke_detected"] is True and v["incident_id"] == "inc-0001" and v["location"] == {"x": 33.0, "y": 11.5}
    assert v["temp_c"] > 150 and v["co2_ppm"] > 2000
    aqi = {r["zone_id"]: r["value"]["aqi"] for r in burning["air_quality"]}
    assert aqi["zone-01"] > 100 > aqi["zone-02"] > 38           # the Guardian's rule: an AQI spike has smoke behind it
    assert aqi["zone-03"] == aqi["zone-02"]                      # the other zones only get what drifts over
    assert {r["sensor_id"]: r["value"]["smoke_detected"] for r in burning["traffic_camera"]}["cam-n2"] is True
    assert v["sim_time_s"] == city.sim_time


def test_when_the_fire_is_out_the_sensor_says_so_once_and_the_air_clears():
    city = _burning_city(30.0)
    city.sensor_readings()
    city.sim.fire.extinguish("fire-0001", city.sim._sim_time)
    city.step(1.0)
    first = _by_type(city.sensor_readings())
    assert [r["value"]["smoke_detected"] for r in first["building_fire"]] == [False]
    assert first["building_fire"][0]["value"]["temp_c"] == 20.0
    city.step(1.0)
    again = _by_type(city.sensor_readings())
    assert "building_fire" not in again                           # no more readings from a building without smoke
    assert {r["value"]["aqi"] for r in again["air_quality"]} == {38}


def test_a_quarantine_can_name_the_fire_sensors_and_air_monitors():
    ids = _burning_city(1.0).device_ids()
    assert {"fire-bld-01-03", "aq-zone-01", "aq-zone-03"} <= ids and len([i for i in ids if i.startswith("fire-")]) == 24


@pytest.fixture
def operator_client():
    city = TwoBlocksCity("city")
    app = create_app(Settings(emit_enabled=False, operator_key=OPERATOR), city)
    return TestClient(app), city


def test_the_operator_sets_a_building_on_fire_and_doing_it_twice_is_a_duplicate(operator_client):
    client, city = operator_client
    h = {"X-Operator-Key": OPERATOR}
    first = client.post("/simulators/ignite_fire", json={"building_id": "bld-02-04"}, headers=h)
    assert first.status_code == 200 and first.json()["status"] == "ignited" and first.json()["building_id"] == "bld-02-04"
    assert client.post("/simulators/ignite_fire", json={"building_id": "bld-02-04"}, headers=h).json()["status"] == "duplicate"
    city.step(10.0)
    assert [f["building_id"] for f in city.sim.fire.open()] == ["bld-02-04"]
    assert city.sim.fire.open()[0]["cause"] == "operator"


def test_the_fire_simulator_refuses_clearly(operator_client):
    client, _ = operator_client
    h = {"X-Operator-Key": OPERATOR}
    assert client.post("/simulators/ignite_fire", json={"building_id": "bld-02-04"}).status_code == 401
    assert client.post("/simulators/ignite_fire", json={"building_id": "bld-99-99"}, headers=h).status_code == 404
    bad = client.post("/simulators/ignite_fire", json={}, headers=h)
    assert bad.status_code == 422 and "building_id" in bad.json()["detail"]


def test_the_operators_fire_does_not_leak_into_the_public_events(operator_client):
    client, city = operator_client
    client.post("/simulators/ignite_fire", json={"building_id": "bld-02-04"}, headers={"X-Operator-Key": OPERATOR})
    asyncio.run(client.app.state.emitter.tick())
    city.step(1.0)
    assert "fire" not in str(client.get("/events").json()).lower().replace("fire-", "").replace("firefight", "")


def test_the_test_book_has_the_fire_scenario_and_the_engine_can_run_it():
    t3 = SCENARIOS["t3"]
    assert t3.engine_scenario in TwoBlocksCity.SCENARIOS
    kinds = [e.kind for e in t3.expected]
    assert kinds[0] == "sim_fire_started" and {"building_fire_reading", "sim_fire_extinguished", "actuator_called"} <= set(kinds)


def _chain():
    spec = importlib.util.spec_from_file_location("incident_chain", Path(__file__).parent / "incident_chain.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["incident_chain"] = module
    spec.loader.exec_module(module)
    return module


def test_the_fire_goes_through_sensor_guardian_brain_truck_and_out():
    result = _chain().run("building-fire", 120.0, record=False, auto=True)
    assert result["missing"] == []
    tl = result["timeline"]
    first = {}
    for e in tl:
        first.setdefault(e["kind"], e)
    order = ["fire_started", "smoke_detected", "first_report", "decision", "unit_dispatched", "unit_pulled_out",
             "unit_arrived", "fire_extinguished", "scene_cleared"]
    times = [first[k]["t"] for k in order]
    assert times == sorted(times), dict(zip(order, times))
    assert {e["action"] for e in tl if e["kind"] == "decision"} == {"dispatch_fire"}   # a burning building needs no ambulance
    assert {e["sensor_id"] for e in tl if e["kind"] == "reading_emitted" and e.get("type") == "building_fire"} == {"fire-bld-01-03"}
    board = result["board"].list()
    assert [i["incident_id"] for i in board] == ["inc-0001"] and board[0]["type"] == "fire"
    assert "smoke_sensor" in board[0]["sources"] and board[0]["building_ids"] == ["bld-01-03"]
    result["board"].update_from_twin(result["city"].responses())   # what the Brain reads from GET /responses
    assert result["board"].list()[0]["status"] == "resolved"      # phase "cleared" (or "closed") means resolved
    result["log"].unlink()


def test_the_mock_brain_only_lists_smoke_not_its_absence():
    rule = load_mock("brain", "fire_brain")
    board = rule.rules.IncidentBoard()
    base = {"sensor_id": "fire-bld-01-03", "type": "building_fire", "zone_id": "zone-01",
            "value": {"building_id": "bld-01-03", "incident_id": "inc-0001", "smoke_detected": False}}
    verdict = {"status": "trusted", "verdict_id": "verdict-1"}
    assert board.observe(base, verdict, 5.0) is None and board.list() == []
    smoke = {**base, "value": {**base["value"], "smoke_detected": True}}
    assert board.observe(smoke, verdict, 6.0)["type"] == "fire"
    assert board.observe(smoke, {"status": "untrusted", "verdict_id": "verdict-2"}, 7.0) is None
