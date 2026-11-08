"""WebSocket streams, verdict-request latency budget, and restart recovery from SQLite."""

from __future__ import annotations

import statistics
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from tests.conftest import BRAIN_API, TWIN_API, Harness


def test_websocket_streams(tmp_path: Path, envelope: Callable[..., dict[str, Any]]) -> None:
    h = Harness(tmp_path)
    with TestClient(h.app) as tc:
        try:
            with tc.websocket_connect("/v1/ws/verdicts") as ws:
                ws.receive_json()
            raise AssertionError("unauthenticated websocket was accepted")
        except WebSocketDisconnect as e:
            assert e.code == 4401
        with tc.websocket_connect("/v1/ws/verdicts", headers={"X-API-Key": BRAIN_API}) as wv, \
                tc.websocket_connect(f"/v1/ws/timeline?api_key={BRAIN_API}") as wt:
            r = tc.post("/v1/readings", json=envelope(), headers={"X-API-Key": TWIN_API})
            assert r.status_code == 200
            msg = wv.receive_json()
            assert msg["type"] == "verdict" and msg["verdict"]["status"] == "trusted"
            kinds = [wt.receive_json()["type"] for _ in range(2)]
            assert kinds == ["reading", "verdict"]
            tc.post("/v1/readings", json=envelope(seq=1), headers={"X-API-Key": TWIN_API})  # replay
            assert wv.receive_json()["verdict"]["reasons"] == ["replay"]
            assert wv.receive_json()["type"] == "alert"


async def test_verdict_request_latency(city: Harness) -> None:
    sensors = list(city.g.state.sensors)
    times = []
    for i in range(200):
        t0 = time.perf_counter()
        r = await city.api("POST", "/v1/verdicts/request", json={"sensor_id": sensors[i % len(sensors)]})
        times.append(time.perf_counter() - t0)
        assert r.status_code == 200
    p95 = statistics.quantiles(times, n=20)[18]
    assert p95 < 0.5, f"p95 {p95 * 1000:.1f} ms"


async def test_restart_recovers_containment_and_verdicts(tmp_path: Path) -> None:
    h1 = Harness(tmp_path)
    await h1.advance(60)
    h1.sim.inject("fake_flood", {})
    bad = h1.of("wl-port-03", await h1.advance(10))[0]
    assert h1.g.containment.is_isolated("wl-port-03")
    await h1.g.containment.quarantine("brain", "caller", "test")
    last_seq = h1.g.state.get("wl-port-03").last_seq  # type: ignore[union-attr]
    replay = h1.sim.sensors["wl-port-03"].last_envelopes[-1]
    await h1.close()

    h2 = Harness(tmp_path)  # same DB file, fresh process state
    assert h2.g.containment.is_isolated("wl-port-03") and h2.g.containment.is_quarantined("brain")
    assert (await h2.api("GET", f"/v1/verdicts/{bad['verdict_id']}")).json()["status"] == "untrusted"
    assert h2.g.state.get("wl-port-03").last_seq == last_seq  # type: ignore[union-attr]
    h2.clock.set(h1.clock.now())
    v = (await h2.push(replay))[0]
    assert v["reasons"] == ["replay"]  # replay protection survives a restart
    r = (await h2.api("POST", "/v1/verdicts/request", json={"sensor_id": "wl-port-03"})).json()
    assert r["status"] == "unknown"  # not heard from since restart → fail safe
    assert h2.g.levels.get("zone-07").value == "elevated"
    await h2.close()
