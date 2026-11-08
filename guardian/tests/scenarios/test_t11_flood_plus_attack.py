"""T11: a real flood (corroborated) plus a fake alarm elsewhere: act on trusted data, ignore the rest."""

from __future__ import annotations

from tests.conftest import Harness, assert_in_order, ev


async def test_t11_real_flood_plus_attack(city: Harness) -> None:
    city.sim.inject("real_flood", {"rainfall_mm_h": 40})
    await city.advance(15 * 60)
    level = city.latest("wl-port-03")
    assert level["status"] == "trusted", level
    assert city.g.state.get("wl-port-03").latest_reading.value["level_m"] > 1.2  # type: ignore[union-attr]

    city.sim.inject("spike", {"sensor_id": "aq-res-01", "value": 380.0})
    fake = city.of("aq-res-01", await city.advance(10))[0]
    assert fake["status"] == "untrusted"

    decision = await city.brain.check_flood("wl-port-03", "zone-07")
    assert decision["decision"] == "forwarded"
    await city.advance(40)
    outcome = [r for r in city.g.verifier.results if r["actuator_id"] == "valve-port-12"]
    assert outcome and outcome[0]["outcome"] == "verified"
    assert city.latest("fm-port-01")["status"] == "trusted"

    assert_in_order(city.events(), [
        ev("verdict", "verdict", sensor_id="wl-port-03", status="trusted"),
        ev("verdict", "verdict", sensor_id="aq-res-01", status="untrusted"),
        ev("alert", "attack_during_incident"),
        ev("decision", "actuator_call", actuator_id="valve-port-12", decision="forwarded"),
        ev("action", "effect_verification", actuator_id="valve-port-12", outcome="verified"),
    ])
