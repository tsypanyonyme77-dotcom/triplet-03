"""T6: the Brain tries to use a quarantined device → blocked with device_quarantined."""

from __future__ import annotations

from tests.conftest import OPS_API, Harness, assert_in_order, ev


async def test_t06_quarantined_device(city: Harness) -> None:
    r = await city.api("POST", "/v1/containment/quarantine", key=OPS_API,
                       json={"device_id": "valve-port-12", "device_type": "actuator", "reason": "tamper alarm",
                             "zone_id": "zone-07"})
    assert r.status_code == 200
    ref = await city.brain.request_verdict("wl-port-03")
    d = await city.brain.send_call("valve-port-12", "set_valve_state", {"state": "closed"}, zone_id="zone-07",
                                   trust_ref=ref["verdict_id"], justification="flood risk")
    assert d["decision"] == "blocked" and "device_quarantined" in d["reasons"]
    assert not [t for t in city.sim.tool_log if t["tool"] == "set_valve_state"]
    assert_in_order(city.events(), [
        ev("containment", "quarantine_device", actuator_id="valve-port-12"),
        ev("decision", "actuator_call", actuator_id="valve-port-12", decision="blocked"),
    ])
