"""T7: the Twin goes silent → every sensor unknown, /health degraded, verdict requests fail safe."""

from __future__ import annotations

from tests.conftest import Harness, assert_in_order, ev


async def test_t07_twin_silent(city: Harness) -> None:
    city.sim.inject("silence", {})
    await city.advance(25)
    await city.g.check_twin()
    health = (await city.client.get("/health")).json()
    assert health["twin"] == "degraded" and health["status"] == "degraded"
    for sid in ("wl-port-03", "fm-port-01", "tc-port-01", "pm-hosp-01"):
        r = (await city.api("POST", "/v1/verdicts/request", json={"sensor_id": sid})).json()
        assert r["status"] == "unknown", sid
    unknown = (await city.api("POST", "/v1/verdicts/request", json={"sensor_id": "never-seen"})).json()
    assert unknown["status"] == "unknown" and unknown["reasons"] == ["unknown_sensor"]
    assert_in_order(city.events(), [
        ev("system", "sensor_stale"),
        ev("system", "twin_health", reachable=False),
        ev("verdict", "verdict", status="unknown"),
    ])
