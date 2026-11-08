"""T9: coordinated spoofing in one zone → under_attack, tightened trust, hysteresis back to normal."""

from __future__ import annotations

from tests.conftest import Harness, assert_in_order, ev


async def test_t09_coordinated_spoofing(city: Harness) -> None:
    city.sim.inject("coordinated", {"zone_id": "zone-08"})
    await city.advance(20)
    threat = (await city.api("GET", "/v1/threat")).json()
    assert threat["zones"]["zone-08"] == "under_attack"
    for sid in ("wl-res-01", "aq-res-01", "tc-res-01"):
        assert city.g.containment.is_isolated(sid), sid

    await city.advance(20)
    # tightened: a reading with no corroboration path stays suspect; 2+ agreeing sources reach trusted
    grid = city.latest("gm-res-01")
    assert grid["status"] == "suspect" and "threat_level_tightened" in grid["reasons"]
    rain = city.latest("rg-res-01")
    assert rain["status"] == "trusted" and rain["trust_score"] >= 0.9

    city.sim.inject("clear", {})
    await city.advance(130)
    assert (await city.api("GET", "/v1/threat")).json()["zones"]["zone-08"] == "elevated"
    await city.advance(125)
    assert (await city.api("GET", "/v1/threat")).json()["zones"]["zone-08"] == "normal"
    assert not city.g.containment.is_isolated("wl-res-01")  # released after clean readings + cooldown

    assert_in_order(city.events(), [
        ev("system", "threat_level", zone_id="zone-08", to="under_attack"),
        ev("alert", "coordinated_spoofing"),
        ev("system", "threat_level", zone_id="zone-08", to="elevated"),
        ev("system", "threat_level", zone_id="zone-08", to="normal"),
    ])
