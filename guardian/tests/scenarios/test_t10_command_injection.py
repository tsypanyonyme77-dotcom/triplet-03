"""T10: actuator calls without trust_ref → blocked; repeated → caller quarantined + command_injection alert."""

from __future__ import annotations

from tests.conftest import Harness, assert_in_order, ev


async def test_t10_command_injection(city: Harness) -> None:
    for i in range(3):
        d = await city.brain.send_call("grid-port", "set_grid_state", {"state": "disconnected"}, zone_id="zone-07",
                                       trust_ref=None, justification=f"no reason {i}")
        assert d["decision"] == "blocked" and "trust_ref_missing" in d["reasons"]
    assert city.g.containment.is_quarantined("brain")
    alerts = (await city.api("GET", "/v1/alerts")).json()
    assert any(a["type"] == "command_injection" for a in alerts)

    ref = await city.brain.request_verdict("pm-port-01")
    d = await city.brain.send_call("grid-port", "set_grid_state", {"state": "disconnected"}, zone_id="zone-07",
                                   trust_ref=ref["verdict_id"], justification="now with a ref")
    assert d["decision"] == "blocked" and "caller_quarantined" in d["reasons"]
    assert not [t for t in city.sim.tool_log if t["tool"] == "set_grid_state"]
    assert_in_order(city.events(), [
        ev("decision", "actuator_call", decision="blocked"),
        ev("containment", "quarantine_device", actuator_id="brain"),
        ev("alert", "command_injection"),
    ])
