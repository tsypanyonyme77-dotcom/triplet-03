"""T1: fake flood at the port (1.80 m vs real 0.40 m, no rain)."""

from __future__ import annotations

from tests.conftest import Harness, assert_in_order, ev


async def test_t01_fake_flood(city: Harness) -> None:
    city.sim.inject("fake_flood", {"sensor_id": "wl-port-03", "level_m": 1.80})
    verdicts = await city.advance(10)
    v = city.of("wl-port-03", verdicts)[0]
    assert v["status"] == "untrusted"
    assert "rate_of_change" in v["reasons"]
    assert any(r.startswith("no_") and r.endswith("_corroboration") for r in v["reasons"])
    assert "no_rainfall_corroboration" in v["reasons"]
    assert v["action_taken"] == "isolate_sensor"
    assert city.g.containment.is_isolated("wl-port-03")

    latest = (await city.api("GET", "/v1/readings/wl-port-03/latest")).json()
    assert latest["rolled_back"] is True and abs(latest["value"]["level_m"] - 0.40) < 0.05

    decision = await city.brain.check_flood("wl-port-03", "zone-07")
    assert decision["brain"] == "ignored"
    assert not [t for t in city.sim.tool_log if t["tool"] == "set_valve_state"]

    assert_in_order(city.events(), [
        ev("reading", "reading", sensor_id="wl-port-03"),
        ev("verdict", "verdict", sensor_id="wl-port-03", status="untrusted"),
        ev("containment", "isolate_sensor", sensor_id="wl-port-03"),
        ev("alert", "spoofing"),
    ])


async def test_isolated_sensor_stays_untrusted_when_its_stream_goes_quiet(city: Harness) -> None:
    """An isolated sensor we have been watching must stay `untrusted` (contained) past the stale boundary, not
    flip to `unknown` — otherwise a momentary gap right at 2x the interval masks the containment signal."""
    city.sim.inject("fake_flood", {"sensor_id": "wl-port-03", "level_m": 1.80})
    await city.advance(10)
    assert city.g.containment.is_isolated("wl-port-03")
    city.sim.inject("silence", {"sensor_id": "wl-port-03"})  # stream stops; well past 2x the 5s interval
    await city.advance(20)
    assert city.g.liveness.is_stale(city.g.state.get("wl-port-03"))  # type: ignore[arg-type]
    v = (await city.api("POST", "/v1/verdicts/request", json={"sensor_id": "wl-port-03"})).json()
    assert v["status"] == "untrusted" and "sensor_isolated" in v["reasons"]
