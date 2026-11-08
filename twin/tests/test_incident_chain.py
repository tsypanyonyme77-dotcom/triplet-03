"""dispatch_unit actuator and the whole incident chain (city -> Guardian mock -> Brain rule -> actuator)."""
import importlib.util
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from twin.city.two_blocks import TwoBlocksCity
from twin.config import Settings
from twin.main import create_app

ROOT = Path(__file__).resolve().parents[2]
API_KEY = "k"


def _chain():
    spec = importlib.util.spec_from_file_location("incident_chain", Path(__file__).parent / "incident_chain.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["incident_chain"] = module
    spec.loader.exec_module(module)
    return module


def _call(unit_type: str, incident_id: str, trust_ref: str | None = "verdict-1") -> dict:
    return {"contract_version": "2026-09-17", "actuator_id": "dispatch-centre-01", "action": "dispatch_unit",
            "params": {"unit_type": unit_type, "incident_id": incident_id}, "requesting_layer": "city_brain",
            "justification": "test", "trust_ref": trust_ref}


def test_dispatch_unit_is_idempotent_and_validated():
    city = TwoBlocksCity("ped-hit")
    city.step(60.0)
    incident = city.sim.call_centre.incidents[0]["id"]
    client = TestClient(create_app(Settings(brain_api_key=API_KEY, emit_enabled=False), city))
    h = {"X-Api-Key": API_KEY}
    first = client.post("/actuators/call", json=_call("ambulance", incident), headers=h).json()["result"]
    again = client.post("/actuators/call", json=_call("ambulance", incident), headers=h).json()["result"]
    assert first["status"] == "dispatched" and first["unit_id"] == "amb1" and first["eta_minutes"] > 0
    assert again == {"status": "duplicate", "unit_id": "amb1", "unit_type": "ambulance", "incident_id": incident}
    assert sum(e["kind"] == "unit_dispatched" for e in city.timeline()) == 1   # one dispatch, however many calls
    unknown = client.post("/actuators/call", json=_call("police", "inc-9999"), headers=h).json()["result"]
    assert unknown["status"] == "rejected" and unknown["reason"] == "unknown_incident"
    assert client.post("/actuators/call", json=_call("tank", incident), headers=h).status_code == 422
    assert client.post("/actuators/call", json=_call("police", incident, trust_ref=None), headers=h).status_code == 403


def test_manual_mode_lists_the_incident_and_nothing_moves_without_an_actuator_call():
    result = _chain().run("ped-hit", 200.0, record=False)
    assert result["missing"] == []
    sim = result["city"].sim
    kinds = {e["kind"] for e in result["timeline"]}
    assert not kinds & {"decision", "unit_dispatched", "unit_pulled_out", "unit_arrived"}
    assert all(u.status == "idle" and u.finished and u.speed == 0.0 for u in sim.units.values())
    board = result["board"].list()
    assert [i["incident_id"] for i in board] == ["inc-0001"] and board[0]["status"] == "reported"
    assert set(board[0]["sources"]) == {"camera", "witness_call"} and board[0]["calls"] >= 1
    accident = sim.accidents[0]
    assert accident["cleared_t"] is None                                     # the incident stays open
    assert sim.cars[accident["car_id"]].status == "crashed"                  # the wreck stays
    assert sim.pedestrians[accident["pedestrian_id"]].status == "injured"    # so does the casualty
    result["log"].unlink()


def test_a_rejected_call_changes_nothing():
    chain = _chain().ChainRun("ped-hit", record=False)
    for _ in range(400):
        chain.step()
    fake = {"incident_id": "inc-9999", "zone_id": "zone-03", "trust_ref": "verdict-00001"}
    result = chain.act("dispatch_police", chain.brain.build_call(fake, "dispatch_police"))
    assert result == {"status": "rejected", "reason": "unknown_incident", "unit_type": "police", "incident_id": "inc-9999"}
    for _ in range(300):
        chain.step()
    assert all(u.status == "idle" and u.speed == 0.0 for u in chain.sim.units.values())


def test_the_chain_reports_decides_dispatches_and_arrives_in_order():
    result = _chain().run("ped-hit", 110.0, record=False, auto=True)
    assert result["missing"] == []
    tl = result["timeline"]
    first = {}
    for e in tl:
        first.setdefault(e["kind"], e)
    order = ["incident", "first_report", "decision", "unit_dispatched", "unit_pulled_out", "unit_arrived"]
    times = [first[k]["t"] for k in order]
    assert times == sorted(times), dict(zip(order, times))
    assert 2.0 <= first["decision"]["t"] - first["first_report"]["t"] <= 5.0   # the Brain's decision delay
    decisions = [e for e in tl if e["kind"] == "decision"]
    assert {e["action"] for e in decisions} == {"dispatch_ambulance", "dispatch_police"}
    arrived = {e["unit_id"] for e in tl if e["kind"] == "unit_arrived"}
    assert "amb1" in arrived
    assert result["log"].exists()
    result["log"].unlink()


def test_auto_mode_answers_a_flood_with_the_fire_truck_police_and_the_pump():
    result = _chain().run("flood", 520.0, record=False, auto=True)
    assert result["missing"] == []
    (decision,) = result["board"].list()   # one incident: the stalled car
    actions = [a["action"] for a in decision["actions"]]
    assert actions == ["dispatch_fire", "dispatch_police", "start_pump"] and decision["type"] == "flood"
    assert [a["status"] for a in decision["actions"]] == ["dispatched", "dispatched", "on"]
    kinds = [e["kind"] for e in result["timeline"]]
    for kind in ("street_flooded", "incident", "pump_started", "rescue_started", "driver_rescued",
                 "pedestrian_rescued", "scene_cleared"):
        assert kind in kinds, kind
    sim = result["city"].sim
    assert sim.responses["inc-0001"]["phase"] == "closed"
    assert "amb1" not in {e.get("unit_id") for e in result["timeline"] if e["kind"] == "unit_dispatched"}
