"""T4: emergency-call flood → call_flood, suspect + throttled, none dropped; duplicate call_id → untrusted."""

from __future__ import annotations

from tests.conftest import Harness, assert_in_order, ev


async def test_t04_call_flood_and_duplicate(city: Harness) -> None:
    city.sim.inject("call_flood", {"zone_id": "zone-08", "count": 8})
    verdicts = city.of("ec-gw-08", await city.step())
    assert len(verdicts) == 8  # none dropped
    assert all(v["status"] == "trusted" for v in verdicts[:5])
    for v in verdicts[5:]:
        assert v["status"] == "suspect"
        assert {"call_flood", "needs_corroboration"} <= set(v["reasons"])
        assert v["action_taken"] == "throttle"

    city.sim.inject("duplicate_call", {})
    dup = city.of("ec-gw-08", await city.step())[0]
    assert dup["status"] == "untrusted" and dup["reasons"] == ["duplicate_call"]

    assert_in_order(city.events(), [
        ev("verdict", "verdict", sensor_id="ec-gw-08", status="suspect"),
        ev("alert", "flood_dos"),
        ev("verdict", "verdict", sensor_id="ec-gw-08", status="untrusted"),
    ])
