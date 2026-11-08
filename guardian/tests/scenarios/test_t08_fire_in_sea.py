"""T8: fire reported in the open sea → semantically impossible → untrusted; no dispatch forwarded."""

from __future__ import annotations

from tests.conftest import Harness, assert_in_order, ev


async def test_t08_fire_in_sea(city: Harness) -> None:
    city.sim.inject("fire_in_sea", {})
    v = city.of("ec-gw-12", await city.step())[0]
    assert v["status"] == "untrusted" and "impossible_location" in v["reasons"]
    ignored = await city.brain.check_fire_call(v, "zone-12", "inc-sea-1")
    assert ignored["brain"] == "ignored"
    forced = await city.brain.send_call("dispatch-central", "dispatch_unit", {"unit_type": "fire"},
                                        zone_id="zone-12", trust_ref=v["verdict_id"], justification="fire call",
                                        incident_id="inc-sea-1")
    assert forced["decision"] == "blocked" and "trust_ref_not_trusted" in forced["reasons"]
    assert not [t for t in city.sim.tool_log if t["tool"] == "dispatch_unit"]
    assert_in_order(city.events(), [
        ev("verdict", "verdict", sensor_id="ec-gw-12", status="untrusted"),
        ev("decision", "actuator_call", actuator_id="dispatch-central", decision="blocked"),
    ])
