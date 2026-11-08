"""T3: replayed readings (valid HMAC, repeated sequence_no) are untrusted; an agreed sequence_reset is not."""

from __future__ import annotations

from tests.conftest import Harness, assert_in_order, ev


async def test_t03_replay_and_sequence_reset(city: Harness) -> None:
    city.sim.inject("replay", {"sensor_id": "wl-port-03"})
    verdicts = await city.step()
    v = city.of("wl-port-03", verdicts)[0]
    assert v["status"] == "untrusted" and v["reasons"] == ["replay"]

    city.sim.inject("sequence_reset", {"sensor_id": "wl-port-03"})
    verdicts = await city.advance(10)
    after = city.of("wl-port-03", verdicts)
    assert after[0]["reading_ref"]["sequence_no"] == 1
    assert all(x["status"] != "untrusted" and "replay" not in x["reasons"] for x in after)

    assert_in_order(city.events(), [
        ev("verdict", "verdict", sensor_id="wl-port-03", status="untrusted"),
        ev("alert", "replay"),
        ev("system", "sequence_reset", sensor_id="wl-port-03"),
        ev("verdict", "verdict", sensor_id="wl-port-03"),
    ])
