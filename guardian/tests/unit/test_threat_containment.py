"""Correlator (each attack pattern + hysteresis), threat levels, alerts, containment (cap, rollback, release)."""

from __future__ import annotations

from guardian.adapters.twin_client import TwinUnavailable
from guardian.containment.quarantine import cooldown_for
from guardian.containment.rollback import latest_usable
from guardian.ingest.state_store import SensorState
from guardian.models import LayerResult, Signal, Status, ThreatLevel, Verdict
from tests.conftest import Harness
from tests.unit.helpers import T0, reading


def verdict(h: Harness, sensor: str = "wl-port-03", zone: str = "zone-07", status: Status = Status.untrusted,
            reasons: list[str] | None = None, l5: str | None = None, **kw: object) -> Verdict:
    results = [LayerResult(layer="L5_corroboration", passed=l5 == "pass", severity="strong" if l5 == "fail" else "info",
                           reason_code="corroborated" if l5 == "pass" else "no_x_corroboration")] if l5 else []
    return Verdict(verdict_id=f"v-{sensor}", sensor_id=sensor, sequence_no=1, zone_id=zone, status=status,
                   trust_score=0.1, reasons=reasons or [], layer_results=results, ts=h.clock.now(),
                   expires_at=h.clock.now(), sensor_type="water_level", **kw)  # type: ignore[arg-type]


def actions(responses: list) -> list[tuple[str, str | None]]:  # type: ignore[type-arg]
    return [(r.action, r.target) for r in responses]


async def test_replay_and_spoofing(harness: Harness) -> None:
    c = harness.g.correlator
    out = c.observe_verdict(verdict(harness, reasons=["replay"]))
    assert ("alert", "wl-port-03") in actions(out) and "wl-port-03" in c.flagged_sources
    assert harness.g.levels.get("zone-07") == ThreatLevel.elevated
    out = c.observe_verdict(verdict(harness, "fm-port-01", reasons=["rate_of_change", "no_rain_corroboration"]))
    assert actions(out)[:2] == [("isolate_sensor", "fm-port-01"), ("alert", "fm-port-01")]
    assert c.planned_action(out) == "isolate_sensor"
    await c.execute(out)
    assert harness.g.containment.is_isolated("fm-port-01")
    # same pattern, same key, inside the window: no duplicate alert
    assert c.observe_verdict(verdict(harness, "fm-port-01", reasons=["rate_of_change"])) == []
    # emergency calls never isolate the call gateway
    call = verdict(harness, "ec-gw-12", "zone-12", reasons=["impossible_location"])
    call.sensor_type = "emergency_call"
    assert all(a != "isolate_sensor" for a, _ in actions(c.observe_verdict(call)))


async def test_coordinated_spoofing_and_hysteresis(harness: Harness) -> None:
    c, lv = harness.g.correlator, harness.g.levels
    for s in ("a", "b", "c"):
        out = c.observe_verdict(verdict(harness, s, "zone-08", reasons=["out_of_range"]))
    assert lv.get("zone-08") == ThreatLevel.under_attack
    assert any(r.pattern == "coordinated_spoofing" for r in out)
    assert c.open_incidents()
    harness.clock.advance(60)
    c.tick()
    assert lv.get("zone-08") == ThreatLevel.under_attack  # still inside the quiet period
    harness.clock.advance(61)
    c.tick()
    assert lv.get("zone-08") == ThreatLevel.elevated
    c.tick()
    assert lv.get("zone-08") == ThreatLevel.elevated  # one step per quiet period
    harness.clock.advance(121)
    c.tick()
    assert lv.get("zone-08") == ThreatLevel.normal and c.open_incidents() == []
    assert not lv.raise_to("zone-08", ThreatLevel.normal, "noop")


async def test_flood_tampering_injection_drift(harness: Harness) -> None:
    c = harness.g.correlator
    assert any(r.pattern == "flood_dos" for r in c.observe_verdict(verdict(harness, status=Status.suspect,
                                                                           reasons=["call_flood"])))
    for i in range(3):
        out = c.observe_ingest_error("hmac_invalid", "wl-port-03", "zone-07", f"bad {i}")
    assert [r.pattern for r in out] == ["tampering"]
    for i in range(3):
        out = c.observe_decision("brain", "grid-port", "zone-07", ["trust_ref_missing"], f"c{i}")
    assert ("quarantine_caller", "brain") in actions(out)
    await c.execute(out)
    assert harness.g.containment.is_quarantined("brain")
    assert c.observe_decision("brain", "grid-port", "zone-07", ["safety_hospital_grid"], "x") == []
    out = c.observe_verdict(verdict(harness, "wl-res-01", "zone-08", Status.suspect, ["slow_drift"]))
    assert ("freeze_baseline", "wl-res-01") in actions(out)
    await c.execute(out)
    assert "wl-res-01" in harness.g.baseline.frozen


async def test_compromised_twin_and_attack_during_incident(harness: Harness) -> None:
    c = harness.g.correlator
    for z in ("zone-07", "zone-08"):
        assert not [r for r in c.observe_verdict(verdict(harness, f"s-{z}", z, Status.suspect, l5="fail"))
                    if r.pattern == "compromised_twin"]
    out = c.observe_verdict(verdict(harness, "s-3", "zone-03", Status.suspect, l5="fail"))
    assert any(r.pattern == "compromised_twin" for r in out)
    real = verdict(harness, "wl-port-03", "zone-07", Status.trusted, l5="pass", corroborated=True, notable=True)
    c.observe_verdict(real)
    out = c.observe_verdict(verdict(harness, "aq-res-01", "zone-08", reasons=["out_of_range"]))
    assert any(r.pattern == "attack_during_incident" for r in out)
    c.add(Signal(type="unrelated", ts=T0))


async def test_execute_never_raises(harness: Harness) -> None:
    from guardian.threat.correlator import Response

    class Boom:
        def can_isolate(self, zone_id: str | None) -> bool:
            return True

        async def isolate(self, *a: object, **k: object) -> object:
            raise RuntimeError("boom")

        async def quarantine(self, *a: object, **k: object) -> object:
            raise RuntimeError("boom")

    c = harness.g.correlator
    c.containment = Boom()
    await c.execute([Response("spoofing", "isolate_sensor", "x", "zone-07")])
    assert any(e["data"].get("kind") == "response_failed" for e in harness.events())


async def test_containment_cap_release_and_rollback(city: Harness) -> None:
    m = city.g.containment
    for s in ("wl-res-01", "aq-res-01", "tc-res-01"):
        assert await m.isolate(s, "zone-08", "test", []) is not None
    assert await m.isolate("pm-res-01", "zone-08", "test", []) is None  # cap reached → alert instead
    assert any(a.type == "isolation_cap_reached" for a in city.g.alerts.recent)
    assert [t["tool"] for t in city.sim.tool_log].count("isolate_sensor") == 3
    assert await m.isolate("wl-res-01", "zone-08", "again", []) is not None  # idempotent

    latest = (await city.api("GET", "/v1/readings/wl-res-01/latest")).json()
    assert latest["rolled_back"] is True and latest["reason"] == "sensor_isolated"
    # clean readings + cooldown → automatic release
    await city.advance(55)
    assert m.is_isolated("wl-res-01")
    await city.advance(15)
    assert not m.is_isolated("wl-res-01")
    assert m.records.get(("wl-res-01", "isolation")) is None
    # re-isolation doubles the cooldown (anti-flapping)
    r = await m.isolate("wl-res-01", "zone-08", "again", [])
    assert r is not None and r.cooldown_s == cooldown_for(60, 2, 1) == 120
    cleared = await m.clear("wl-res-01", "operator", manual=True)
    assert cleared and not await m.clear("wl-res-01", "again")


async def test_quarantine_needs_reason_and_twin_failure_enforces_locally(harness: Harness) -> None:
    m = harness.g.containment
    import pytest

    with pytest.raises(ValueError):
        await m.quarantine("valve-port-12", "actuator", "")

    async def down(name: str, payload: dict) -> dict:  # type: ignore[type-arg]
        raise TwinUnavailable("down")

    harness.g.twin.call_tool = down  # type: ignore[method-assign]
    await m.quarantine("valve-port-12", "actuator", "tamper")
    assert m.is_quarantined("valve-port-12") and m.contained_reason("valve-port-12") == "device_quarantined"
    assert any(e["data"].get("kind") == "twin_unreachable" for e in harness.events())


def test_rollback_view_variants() -> None:
    from collections import deque

    s = SensorState("x", "water_level", "zone-07", deque())
    assert latest_usable(s, "sensor_isolated", False)["value"] is None
    s.latest_reading = reading(value={"level_m": 1.8})
    s.latest_verdict = Verdict(verdict_id="v", sensor_id="x", sequence_no=1, status=Status.untrusted,
                               trust_score=0.1, ts=T0, expires_at=T0)
    s.lkg = reading(value={"level_m": 0.4})
    view = latest_usable(s, None, False)
    assert view["rolled_back"] and view["value"] == {"level_m": 0.4} and view["reason"] == "latest_untrusted"
    s.latest_verdict.status = Status.suspect
    view = latest_usable(s, None, True)
    assert not view["rolled_back"] and view["status"] == "unknown" and view["reason"] == "stale"
