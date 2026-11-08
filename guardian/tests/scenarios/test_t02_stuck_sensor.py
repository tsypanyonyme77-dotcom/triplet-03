"""T2: stuck sensor (flatline → suspect) then dead sensor (silence → stale → unknown)."""

from __future__ import annotations

from tests.conftest import Harness, assert_in_order, ev


async def test_t02_stuck_then_dead(city: Harness) -> None:
    city.sim.inject("stuck", {"sensor_id": "wl-port-03"})
    await city.advance(5 * 52)
    v = city.latest("wl-port-03")
    assert v["status"] == "suspect" and "flatline" in v["reasons"]

    city.sim.inject("silence", {"sensor_id": "wl-port-03"})
    await city.advance(15)
    r = (await city.api("POST", "/v1/verdicts/request", json={"sensor_id": "wl-port-03"})).json()
    assert r["status"] == "unknown" and "stale" in r["reasons"]
    assert (await city.api("GET", "/v1/sensors/wl-port-03/status")).json()["stale"] is True

    assert_in_order(city.events(), [
        ev("verdict", "verdict", sensor_id="wl-port-03", status="suspect"),
        ev("system", "sensor_stale", sensor_id="wl-port-03"),
        ev("verdict", "verdict", sensor_id="wl-port-03", status="unknown"),
    ])
