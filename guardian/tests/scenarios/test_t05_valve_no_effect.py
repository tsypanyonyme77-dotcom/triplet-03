"""T5: valve ordered closed, Twin says ok, flow unchanged → actuator_failure; untrusted flow sensor → unknown."""

from __future__ import annotations

from tests.conftest import OPS_API, Harness, assert_in_order, ev


async def test_t05_valve_stuck(city: Harness) -> None:
    city.sim.inject("valve_stuck", {"actuator_id": "valve-port-12"})
    ref = await city.brain.request_verdict("wl-port-03")
    assert ref["status"] == "trusted"
    d = await city.brain.send_call("valve-port-12", "set_valve_state", {"state": "closed"}, zone_id="zone-07",
                                   trust_ref=ref["verdict_id"], justification="flood risk zone-07")
    assert d["decision"] == "forwarded" and d["twin_reply"]["status"] == "ok"
    await city.advance(35)
    outcome = [r for r in city.g.verifier.results if r["actuator_id"] == "valve-port-12"]
    assert outcome[-1]["outcome"] == "no_effect"
    alerts = (await city.api("GET", "/v1/alerts")).json()
    failure = [a for a in alerts if a["type"] == "actuator_failure"]
    assert failure and "backup" in failure[0]["suggested_response"]

    ref2 = await city.brain.request_verdict("wl-port-03")
    again = await city.brain.send_call("valve-port-12", "set_valve_state", {"state": "closed"}, zone_id="zone-07",
                                       trust_ref=ref2["verdict_id"], justification="retry")
    assert again["decision"] == "blocked" and "actuator_unreliable" in again["reasons"]

    assert_in_order(city.events(), [
        ev("decision", "actuator_call", actuator_id="valve-port-12", decision="forwarded"),
        ev("action", "effect_verification", actuator_id="valve-port-12", outcome="no_effect"),
        ev("alert", "actuator_failure"),
    ])


async def test_t05_untrusted_flow_sensor_gives_unknown(city: Harness) -> None:
    ref = await city.brain.request_verdict("wl-res-01")
    d = await city.brain.send_call("valve-res-02", "set_valve_state", {"state": "closed"}, zone_id="zone-08",
                                   trust_ref=ref["verdict_id"], justification="flood risk zone-08")
    assert d["decision"] == "forwarded"
    r = await city.api("POST", "/v1/containment/quarantine", key=OPS_API,
                       json={"device_id": "fm-res-01", "device_type": "sensor", "reason": "maintenance"})
    assert r.status_code == 200
    await city.advance(35)
    outcome = [x for x in city.g.verifier.results if x["actuator_id"] == "valve-res-02"]
    assert outcome[-1]["outcome"] == "unknown"
    assert not city.g.containment.is_unreliable("valve-res-02")
