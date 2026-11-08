"""The Guardian's contract 1.0: readings rendered in its dialect and pushed in batches, and the calls it
forwards to POST /tools/{action} (guardian/INTERFACE.md sections 3, 4.1 and 4.3)."""
import asyncio
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from twin.city.two_blocks import TwoBlocksCity
from twin.config import Settings
from twin.events import EventLog
from twin.main import create_app
from twin.partners.guardian_dialect import GuardianDialect, guardian_hmac
from twin.partners.guardian_push import GuardianPush

# the Guardian's sensor registry (guardian/config/sensor_registry.yaml): `value` must hold exactly these fields
REGISTRY = {"traffic_camera": {"vehicle_count", "avg_speed_kmh", "congestion_score"}, "water_level": {"level_m"},
            "air_quality": {"aqi", "smoke"}, "emergency_call": {"call_id", "incident_type", "caller_id"},
            "rain_gauge": {"rainfall_mm_h"}, "flow_meter": {"flow_rate_m3s"}}
ENVELOPE = {"contract_version", "sensor_id", "sensor_type", "zone_id", "timestamp", "sequence_no", "value", "sequence_reset", "hmac"}


def test_the_guardians_worked_example_signs_the_same():
    envelope = {"contract_version": "1.0", "sensor_id": "wl-port-03", "sensor_type": "water_level", "sequence_no": 4821,
                "sequence_reset": False, "timestamp": "2026-11-02T14:03:18Z", "value": {"level_m": 1.8}, "zone_id": "zone-07"}
    assert guardian_hmac(envelope, "example-twin-key") == "30d230a2d99a160d20260477e151fa91c58e98d6d76875d0d7fffcdc1195911a"


def _readings(scenario, seconds):
    city = TwoBlocksCity(scenario)
    city.step(seconds)
    app = create_app(Settings(emit_enabled=False, live=False), city)
    return app.state.emitter.build_readings()


def test_every_rendered_reading_holds_exactly_what_the_guardian_registry_asks():
    readings = _readings("building-fire", 48.0) + _readings("ped-hit", 60.0) + _readings("flood", 90.0)
    dialect = GuardianDialect("k")
    rendered = [e for r in readings for e in dialect.render(r)]
    kinds = {e["sensor_type"] for e in rendered}
    assert kinds == set(REGISTRY)
    for e in rendered:
        assert set(e) == ENVELOPE and e["contract_version"] == "1.0"
        assert set(e["value"]) == REGISTRY[e["sensor_type"]], e
        assert e["hmac"] == guardian_hmac(e, "k")
    calls = [e for e in rendered if e["sensor_type"] == "emergency_call"]
    assert calls and all(c["value"]["incident_type"] in {"fire", "flood", "accident", "medical", "crime"} for c in calls)
    assert all(isinstance(e["value"]["smoke"], bool) for e in rendered if e["sensor_type"] == "air_quality")


def test_types_the_guardian_does_not_know_are_not_sent_and_ids_and_numbers_are_ours():
    readings = _readings("ped-hit", 60.0)
    dialect = GuardianDialect("k")
    for r in readings:
        out = dialect.render(r)
        if r["type"] in ("cctv_anomaly", "building_fire", "unit_status"):
            assert out == []
        elif r["type"] == "water_level":
            assert [(e["sensor_type"], e["sensor_id"]) for e in out] == [("water_level", r["sensor_id"]),
                                                                         ("flow_meter", "flow-" + r["sensor_id"][3:])]
        elif out:
            assert out[0]["sensor_id"] == r["sensor_id"] and out[0]["sequence_no"] == r["sequence_no"]


def test_sequence_reset_is_sent_once_per_sensor():
    city = TwoBlocksCity("city", 1)
    city.step(2.0)
    app = create_app(Settings(emit_enabled=False, live=False), city)
    dialect = GuardianDialect("k")
    first = [e for r in app.state.emitter.build_readings() for e in dialect.render(r)]
    city.step(1.0)
    second = [e for r in app.state.emitter.build_readings() for e in dialect.render(r)]
    assert first and all(e["sequence_reset"] for e in first)
    assert second and not any(e["sequence_reset"] for e in second)


def test_a_batch_goes_to_v1_readings_with_the_key_and_refusals_are_reported():
    seen = []

    def guardian(request: httpx.Request) -> httpx.Response:
        batch = json.loads(request.content)
        seen.append((str(request.url), request.headers.get("x-api-key"), batch))
        results = [{"verdict": {"status": "trusted"}} for _ in batch]
        results[0] = {"error": {"error": "schema_invalid", "message": "unknown field 'x'", "field": "value.x"}}
        return httpx.Response(200, json={"results": results})

    events = EventLog("twin")
    push = GuardianPush("http://guardian:8003/v1/readings", "twin-key", GuardianDialect("k"), events)

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(guardian)) as client:
            await push.push(client, _readings("ped-hit", 60.0))

    asyncio.run(run())
    ((url, key, batch),) = seen
    assert url == "http://guardian:8003/v1/readings" and key == "twin-key" and len(batch) > 5
    (failed,) = [e for e in events.recent(10) if e["kind"] == "delivery_failed"]
    assert "schema_invalid" in failed["message"] and failed["data"]["count"] == 1


def _tools(settings=None):
    city = TwoBlocksCity("ped-hit")
    city.step(60.0)
    app = create_app(settings or Settings(emit_enabled=False, live=False), city)
    return TestClient(app), city


def _forwarded(call_id="call-0001", station="dispatch-hospital", unit="ambulance", incident="inc-0042"):
    return {"call_id": call_id, "actuator_id": "dispatch-central", "action": "dispatch_unit",
            "params": {"unit_type": unit, "station_id": station}, "zone_id": "zone-03", "requesting_layer": "brain",
            "trust_ref": "verdict-88213", "justification": "accident on the south street", "incident_id": incident}


def test_a_forwarded_dispatch_is_answered_in_the_guardians_shape():
    client, city = _tools()
    reply = client.post("/tools/dispatch_unit", json=_forwarded()).json()
    assert reply["status"] == "ok" and reply["unit_id"] == "amb1" and reply["eta_s"] > 0 and reply["reverts_at"] is None
    assert reply["current_state"]["incident_id"] == "inc-0042" and city.sim.units["amb1"].station_id == "hospital"
    resent = client.post("/tools/dispatch_unit", json=_forwarded()).json()
    assert resent["status"] == "ok" and resent["current_state"]["replayed"] is True
    other_call = client.post("/tools/dispatch_unit", json=_forwarded(call_id="call-0002")).json()
    assert other_call["status"] == "ok" and other_call["current_state"]["status"] == "duplicate"


def test_the_guardians_containment_reaches_our_devices():
    client, _ = _tools()
    quarantine = {"call_id": "gcall-1", "actuator_id": "flow-dip-2-3", "action": "quarantine_device",
                  "params": {"device_id": "flow-dip-2-3"}, "zone_id": "zone-03", "requesting_layer": "guardian", "trust_ref": None,
                  "justification": "flow meter disagrees with its water level"}
    reply = client.post("/tools/quarantine_device", json=quarantine).json()
    assert reply["status"] == "ok" and reply["current_state"]["device_id"] == "wl-dip-2-3"
    assert [d["device_id"] for d in client.get("/quarantine").json()["devices"]] == ["wl-dip-2-3"]
    station = {**quarantine, "call_id": "gcall-2", "actuator_id": "dispatch-hospital", "params": {"device_id": "dispatch-hospital"}}
    assert client.post("/tools/quarantine_device", json=station).json()["status"] == "ok"
    blocked = client.post("/tools/dispatch_unit", json=_forwarded(call_id="call-0003")).json()
    assert blocked["status"] == "rejected" and blocked["current_state"]["reason"] == "station_quarantined"
    not_guardian = {**quarantine, "call_id": "gcall-3", "requesting_layer": "brain"}
    assert client.post("/tools/quarantine_device", json=not_guardian).json()["status"] == "rejected"


def test_what_the_twin_cannot_do_is_rejected_not_an_http_error():
    client, _ = _tools()
    valve = {"call_id": "call-9", "actuator_id": "valve-port-12", "action": "set_valve_state", "params": {"state": "closed"},
             "zone_id": "zone-07", "requesting_layer": "brain", "trust_ref": "verdict-1", "justification": "flood"}
    resp = client.post("/tools/set_valve_state", json=valve)
    assert resp.status_code == 200 and resp.json()["status"] == "rejected" and resp.json()["reason"] == "not_supported"
    no_trust = {**_forwarded(call_id="call-10"), "trust_ref": None}
    assert client.post("/tools/dispatch_unit", json=no_trust).json()["status"] == "rejected"


def test_a_tools_key_is_required_once_configured():
    client, _ = _tools(Settings(emit_enabled=False, live=False, tools_api_key="tk"))
    assert client.post("/tools/dispatch_unit", json=_forwarded()).status_code == 401
    assert client.post("/tools/dispatch_unit", json=_forwarded(), headers={"X-API-Key": "tk"}).json()["status"] == "ok"


def _ped_hit_emitter(**settings):
    city = TwoBlocksCity("ped-hit")
    city.step(60.0)
    return create_app(Settings(emit_enabled=False, live=False, guardian_dialect="guardian-v1",
                               guardian_ingest_url="http://guardian:8003/v1/readings", **settings), city)


def test_the_brain_is_offered_only_what_the_guardian_can_judge():
    app = _ped_hit_emitter()
    readings = asyncio.run(app.state.emitter.tick())
    assert {"cctv_anomaly", "traffic_camera"} <= {r["type"] for r in readings}     # the camera does flag the crash
    offered = app.state.reading_log.page(0, 1000)["readings"]
    assert {r["type"] for r in offered} == {"traffic_camera", "water_level", "rainfall", "air_quality", "emergency_call"}
    assert all(r["value"].get("category") != "other" for r in offered)             # a call the Guardian has no type for


def test_extended_types_go_to_the_guardian_and_the_brain_once_configured():
    app = _ped_hit_emitter(guardian_extended_types=("cctv_anomaly",))
    readings = asyncio.run(app.state.emitter.tick())
    assert "cctv_anomaly" in {r["type"] for r in app.state.reading_log.page(0, 1000)["readings"]}
    dialect = GuardianDialect("k", ("cctv_anomaly",))
    (rendered,) = [e for r in readings if r["type"] == "cctv_anomaly" for e in dialect.render(r)]
    assert set(rendered["value"]) == {"anomaly_type", "confidence"} and rendered["sensor_id"] == "cam-n2-cctv"


def test_a_type_with_no_mapping_stops_the_start_with_a_clear_error():
    with pytest.raises(ValueError, match="GUARDIAN_EXTENDED_TYPES"):
        GuardianDialect("k", ("citizen_activity",))
