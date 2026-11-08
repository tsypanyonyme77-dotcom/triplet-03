"""API surface: auth, error model, every endpoint, scenario header, pull-mode ingest, transport selection."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from guardian.adapters.twin_client import make_twin_client
from guardian.clock import FakeClock
from guardian.config import TwinCfg
from tests.conftest import OPS_API, TWIN_API, Harness


async def test_auth_and_error_model(harness: Harness) -> None:
    r = await harness.client.post("/v1/verdicts/request", json={"sensor_id": "x"})
    assert r.status_code == 401 and r.json() == {"error": "auth_required", "message": "missing or invalid X-API-Key",
                                                 "field": None}
    r = await harness.api("POST", "/v1/verdicts/request", key="wrong", json={"sensor_id": "x"})
    assert r.status_code == 401
    r = await harness.api("POST", "/v1/verdicts/request", json={"sensor": "x"})
    assert r.status_code == 422 and r.json()["error"] == "schema_invalid" and r.json()["field"] == "sensor_id"
    assert (await harness.client.get("/health")).status_code == 200
    assert (await harness.client.get("/openapi.json")).status_code == 200


async def test_readings_endpoint_shapes(harness: Harness, envelope: Callable[..., dict[str, Any]]) -> None:
    post = lambda body: harness.client.post("/v1/readings", content=body,  # noqa: E731
                                            headers={"X-API-Key": TWIN_API, "content-type": "application/json"})
    assert (await post(b"{not json")).json()["error"] == "schema_invalid"
    assert (await post(b'"a string"')).status_code == 400
    assert (await post(b"[]")).json() == {"results": []}
    r = await harness.api("POST", "/v1/readings", key=TWIN_API, json=[envelope(), {"contract_version": "1.0"},
                                                                     envelope(seq=2, key="bad")])
    res = r.json()["results"]
    assert res[0]["verdict"]["status"] == "trusted"
    assert res[1]["error"]["error"] == "schema_invalid"
    assert res[2]["verdict"]["reasons"] == ["hmac_invalid"]
    big = await harness.api("POST", "/v1/readings", key=TWIN_API, json=[{}] * 1001)
    assert big.status_code == 413


async def test_verdict_endpoints(harness: Harness, envelope: Callable[..., dict[str, Any]]) -> None:
    v = (await harness.push(envelope()))[0]
    got = (await harness.api("GET", f"/v1/verdicts/{v['verdict_id']}")).json()
    assert got == v
    assert (await harness.api("GET", "/v1/verdicts/nope")).json()["error"] == "verdict_not_found"
    by_seq = (await harness.api("POST", "/v1/verdicts/request", json={"sensor_id": "wl-port-03",
                                                                       "sequence_no": 1})).json()
    assert by_seq["verdict_id"] == v["verdict_id"]
    missing = (await harness.api("POST", "/v1/verdicts/request", json={"sensor_id": "wl-port-03",
                                                                        "sequence_no": 99})).json()
    assert missing["status"] == "unknown" and missing["reasons"] == ["no_verdict"]
    call = envelope("ec-gw-07", "emergency_call", value={"call_id": "c1", "incident_type": "medical",
                                                         "caller_id": "a"})
    first = (await harness.push(call))[0]
    harness.clock.advance(31)  # event-driven sensors never go stale, but their verdicts expire
    re = (await harness.api("POST", "/v1/verdicts/request", json={"sensor_id": "ec-gw-07"})).json()
    assert re["verdict_id"] != first["verdict_id"] and re["status"] == "trusted"
    harness.clock.advance(-31)
    st = (await harness.api("GET", "/v1/sensors/wl-port-03/status")).json()
    assert st["trust_state"] == "trusted" and not st["isolated"] and st["last_sequence_no"] == 1
    assert (await harness.api("GET", "/v1/sensors/nope/status")).status_code == 404
    assert (await harness.api("GET", "/v1/readings/nope/latest")).status_code == 404
    latest = (await harness.api("GET", "/v1/readings/wl-port-03/latest")).json()
    assert latest["rolled_back"] is False and latest["value"] == {"level_m": 0.4}


async def test_signature_helper(harness: Harness, envelope: Callable[..., dict[str, Any]]) -> None:
    from mocks.common.signing import verify_verdict
    from tests.conftest import GUARDIAN_KEY

    sample = (await harness.api("GET", "/v1/verify/signature")).json()
    assert sample["valid"] and verify_verdict(sample["verdict"], GUARDIAN_KEY)
    v = (await harness.push(envelope()))[0]
    one = (await harness.api("GET", "/v1/verify/signature", params={"verdict_id": v["verdict_id"]})).json()
    assert one["valid"] and one["verdict"] == v
    assert (await harness.api("GET", "/v1/verify/signature", params={"verdict_id": "x"})).status_code == 404


async def test_containment_threat_alerts_endpoints(city: Harness) -> None:
    city.sim.inject("fake_flood", {})
    await city.advance(10)
    act = (await city.api("GET", "/v1/containment")).json()["active"]
    assert [a["device_id"] for a in act] == ["wl-port-03"]
    threat = (await city.api("GET", "/v1/threat")).json()
    assert threat["zones"]["zone-07"] == "elevated" and threat["incidents"]
    alerts = (await city.api("GET", "/v1/alerts")).json()
    assert alerts and (await city.api("GET", "/v1/alerts", params={"since": "2030-01-01T00:00:00Z"})).json() == []
    assert (await city.api("POST", "/v1/containment/quarantine", json={"device_id": "x", "device_type": "sensor",
                                                                         "reason": "r"})).status_code == 403
    r = await city.api("POST", "/v1/containment/clear", json={"device_id": "wl-port-03", "reason": "checked"})
    assert r.status_code == 200 and r.json()["cleared"][0]["kind"] == "isolation"
    r = await city.api("POST", "/v1/containment/clear", json={"device_id": "wl-port-03", "reason": "again"})
    assert r.status_code == 404 and r.json()["error"] == "not_contained"
    assert (await city.api("POST", "/v1/containment/quarantine", key=OPS_API,
                           json={"device_id": "x", "device_type": "sensor", "reason": "r"})).status_code == 200


async def test_scenario_header_reaches_audit_log(harness: Harness, envelope: Callable[..., dict[str, Any]]) -> None:
    await harness.client.post("/v1/readings", json=envelope(), headers={"X-API-Key": TWIN_API, "X-Scenario-Id": "T1"})
    assert {e["scenario_id"] for e in harness.events() if e["type"] in ("reading", "verdict")} == {"T1"}


async def test_pull_mode_ingest(harness: Harness) -> None:
    got: list[dict[str, Any]] = []

    async def collect(items: list[dict[str, Any]]) -> None:
        got.extend(items)
        await harness.g.pipeline.ingest_many(items)

    harness.clock.advance(15)
    assert await harness.twin_client.poll_once(collect) > 0
    assert harness.twin_client.cursor == len(got)
    assert harness.g.state.get("wl-port-03") is not None
    assert await harness.twin_client.health()


def test_transport_selection_is_lazy() -> None:
    cfg = TwinCfg(base_url="http://localhost:1")
    assert make_twin_client(cfg, FakeClock()).transport == "rest"
    for transport, mod in (("mcp", "mcp"), ("mqtt", "aiomqtt")):
        try:
            __import__(mod)
        except ImportError:
            with pytest.raises(RuntimeError, match="optional dependency"):
                make_twin_client(cfg.model_copy(update={"transport": transport}), FakeClock())
        else:
            assert make_twin_client(cfg.model_copy(update={"transport": transport}), FakeClock()).transport == transport


async def test_pipeline_fail_safe(harness: Harness, envelope: Callable[..., dict[str, Any]]) -> None:
    def boom(*_: Any) -> Any:
        raise RuntimeError("detector bug")

    harness.g.pipeline.l3a.check = boom  # type: ignore[method-assign]
    v = (await harness.push(envelope()))[0]
    assert v["status"] == "unknown" and v["reasons"] == ["internal_error"]
    harness.g.pipeline._request = boom  # type: ignore[method-assign]
    r = (await harness.api("POST", "/v1/verdicts/request", json={"sensor_id": "wl-port-03"})).json()
    assert r["status"] == "unknown"
    assert any(e["data"].get("kind") == "pipeline_error" for e in harness.events())
