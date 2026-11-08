"""Call auditor (authorisation, policy, rate limits), expectation DSL, effect verifier (all failure types)."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest

from guardian.actuator_watch.effect_verifier import DslError, Predicate, parse_expect
from guardian.models import ActuatorCall, Status, ThreatLevel
from tests.conftest import Harness


def call(actuator: str = "valve-port-12", action: str = "set_valve_state", params: dict[str, Any] | None = None,
         trust_ref: str | None = None, zone: str | None = "zone-07", **kw: Any) -> ActuatorCall:
    return ActuatorCall(call_id=f"c-{actuator}-{action}-{trust_ref}", actuator_id=actuator, action=action,
                        params=params if params is not None else {"state": "closed"}, zone_id=zone,
                        trust_ref=trust_ref, justification="test", **kw)


# ---------------- DSL
def test_dsl_parse_and_eval() -> None:
    p = parse_expect("drop_pct >= 80")
    assert p == Predicate("drop_pct", ">=", 80.0)
    assert p.holds(1.2, 0.1) and not p.holds(1.2, 1.1) and not p.holds(None, 0.0)
    assert p.progress(1.0, 0.6) == pytest.approx(0.5)
    r = parse_expect("rise_pct >= 10")
    assert r.holds(50, 56) and not r.holds(50, 52) and r.holds(0, 1)
    v = parse_expect("value <= 5")
    assert v.holds(None, 4.0) and not v.holds(500, 6)
    assert v.progress(505, 255) == pytest.approx(0.5) and Predicate("value", "<=", 5).progress(5, 5) == 1.0
    assert parse_expect("value >= 3").holds(0, 3)
    assert parse_expect("present").metric == "present"
    for bad in ("__import__('os')", "drop_pct <= 3", "value == 1", "flow > 2", ""):
        with pytest.raises(DslError):
            parse_expect(bad)


# ---------------- auditor
async def test_auditor_authorisation(city: Harness) -> None:
    a, g = city.g.auditor, city.g
    ref = g.pipeline.request_verdict("wl-port-03")
    assert ref.status == Status.trusted
    assert (await a.handle(call(trust_ref=None), "brain")).reasons == ["trust_ref_missing"]
    assert (await a.handle(call(trust_ref="verdict-nope"), "brain")).reasons == ["trust_ref_unknown"]
    bad = g.engine.unknown("wl-port-03", "stale", zone_id="zone-07")
    assert "trust_ref_not_trusted" in (await a.handle(call(trust_ref=bad.verdict_id), "brain")).reasons
    other = g.pipeline.request_verdict("aq-hosp-01")  # zone-03 is not zone-07 or adjacent
    assert "trust_ref_zone_mismatch" in (await a.handle(call(trust_ref=other.verdict_id), "brain")).reasons
    city.clock.advance(31)
    assert "trust_ref_expired" in (await a.handle(call(trust_ref=ref.verdict_id), "brain")).reasons
    fresh = g.pipeline.request_verdict("wl-port-03")
    await g.containment.isolate("wl-port-03", "zone-07", "test", [])
    assert "sensor_isolated" in (await a.handle(call(trust_ref=fresh.verdict_id), "brain")).reasons
    assert "containment_reserved" in (await a.handle(call(action="isolate_sensor"), "brain")).reasons
    assert "unknown_actuator" in (await a.handle(call(actuator="nope"), "brain")).reasons


async def test_auditor_policies(city: Harness) -> None:
    a, g = city.g.auditor, city.g
    hosp = g.pipeline.request_verdict("pm-hosp-01").verdict_id
    d = await a.handle(call("grid-hosp", "set_grid_state", {"state": "disconnected"}, hosp, "zone-03"), "brain")
    assert d.decision == "blocked" and "safety_hospital_grid" in d.reasons
    ref = g.pipeline.request_verdict("wl-port-03").verdict_id
    first = await a.handle(call("dispatch-central", "dispatch_unit", {"unit_type": "police"}, ref,
                                incident_id="inc-1"), "brain")
    assert first.decision == "forwarded" and first.twin_reply and first.twin_reply["current_state"]["unit_id"]
    dup = await a.handle(call("dispatch-central", "dispatch_unit", {"unit_type": "police"}, ref,
                              incident_id="inc-1"), "brain")
    assert "duplicate_dispatch" in dup.reasons
    no_incident = await a.handle(call("dispatch-central", "dispatch_unit", {}, ref), "brain")
    assert "incident_id_missing" in no_incident.reasons
    sea = g.pipeline.request_verdict("aq-sea-01").verdict_id
    assert "no_road_access" in (await a.handle(call("dispatch-central", "dispatch_unit", {}, sea, "zone-12",
                                                    incident_id="inc-2"), "brain")).reasons
    for _ in range(6):
        await a.handle(call("sig-port-01", "set_signal", {"state": "red", "duration_s": 5}, ref), "ops")
    assert "rate_limited" in (await a.handle(call("sig-port-01", "set_signal", {"state": "red"}, ref), "ops")).reasons


async def test_auditor_twin_down_and_odd_hours(city: Harness) -> None:
    g = city.g
    ref = g.pipeline.request_verdict("wl-port-03").verdict_id
    city.sim.silence_all = True
    d = await g.auditor.handle(call(trust_ref=ref), "brain")
    assert d.decision == "blocked" and "twin_unreachable" in d.reasons
    city.sim.silence_all = False
    city.clock.set(city.clock.now().replace(hour=1))  # 02:00 local
    g.state.get("wl-port-03").latest_verdict.expires_at = city.clock.now() + timedelta(seconds=30)  # type: ignore[union-attr]
    d = await g.auditor.handle(call(trust_ref=ref, params={"state": "open"}), "brain")
    assert d.decision == "forwarded" and "odd_hour_action" in d.reasons


# ---------------- effect verifier
async def _forward(h: Harness, c: ActuatorCall) -> list[str]:
    reply = h.sim.tool(c.action, c.model_dump())
    return await h.g.verifier.expect(c, reply)


def outcomes(h: Harness, actuator: str) -> list[str]:
    return [r["outcome"] for r in h.g.verifier.results if r["actuator_id"] == actuator]


async def test_verified_and_no_effect(city: Harness) -> None:
    await _forward(city, call())
    await city.advance(15)
    assert outcomes(city, "valve-port-12") == ["verified"]
    city.sim.stuck_actuators.add("valve-res-02")
    await _forward(city, call("valve-res-02", zone="zone-08"))
    await city.advance(35)
    assert outcomes(city, "valve-res-02") == ["no_effect"]
    assert city.g.containment.is_unreliable("valve-res-02")


async def test_partial_and_late_effect(city: Harness) -> None:
    await _forward(city, call("grid-port", "set_grid_state", {"state": "disconnected"}))
    city.sim.grid_connected["zone-07"] = True  # undo: nothing happened yet
    city.sim.overrides.clear()
    from mocks.twin_mock.sim import Override

    city.sim.overrides["pm-port-01"] = Override("fixed", {"load_kw": 300.0})  # ~40% of the way
    await city.advance(25)
    assert outcomes(city, "grid-port") == ["partial_effect"]
    city.sim.overrides["pm-port-01"] = Override("fixed", {"load_kw": 2.0})
    await city.advance(15)
    assert outcomes(city, "grid-port") == ["partial_effect", "late_effect"]


async def test_wrong_effect(city: Harness) -> None:
    city.sim.stuck_actuators.add("valve-port-12")
    await _forward(city, call())
    city.sim.valve_closed["zone-08"] = True  # the other zone's valve shut instead
    await city.advance(35)
    assert outcomes(city, "valve-port-12")[0] == "wrong_effect"


async def test_reply_contradicts_order_and_reverted_early(city: Harness) -> None:
    v = city.g.verifier
    assert await v.expect(call(), {"status": "ok", "current_state": {"state": "open"}}) == ["reply_contradicts_order"]
    now = city.clock.now()
    early = (now + timedelta(seconds=10)).isoformat().replace("+00:00", "Z")
    sig = call("sig-port-01", "set_signal", {"state": "green", "duration_s": 60})
    assert await v.expect(sig, {"status": "ok", "current_state": {"state": "green"}, "reverts_at": early}) == \
        ["reverted_early"]
    # effect seen, then vanishes before the ordered end
    await _forward(city, sig)
    await city.advance(15)
    assert "verified" in outcomes(city, "sig-port-01")
    city.sim.green_until.clear()
    await city.advance(20)
    assert outcomes(city, "sig-port-01")[-1] == "reverted_early"


async def test_unauthorised_effect_and_dispatch(city: Harness) -> None:
    city.sim.valve_closed["zone-07"] = True  # nobody asked
    await city.advance(20)
    assert "unauthorised_effect" in outcomes(city, "valve-port-12")
    v = city.g.verifier
    disp = call("dispatch-central", "dispatch_unit", {"unit_type": "fire"}, incident_id="i")
    assert await v.expect(disp, {"status": "ok", "current_state": {}}) == ["no_effect"]
    assert await v.expect(disp, {"status": "ok", "current_state": {"unit_id": "f-1", "eta_s": 60}}) == []
    assert outcomes(city, "dispatch-central") == ["no_effect", "verified"]


async def test_no_effect_still_caught_in_an_elevated_zone(city: Harness) -> None:
    """In a raised-threat zone the verify sensor is capped to `suspect` (corroboration is skipped for a sensor
    whose change we explained with our own order). A self-consistent `suspect` reading must still let the verifier
    conclude `no_effect` — otherwise actuator checks silently stop working exactly during an incident."""
    city.g.levels.raise_to("zone-07", ThreatLevel.elevated, "test")
    city.sim.stuck_actuators.add("valve-port-12")
    await _forward(city, call())
    await city.advance(35)
    assert city.g.state.get("fm-port-01").latest_verdict.status == Status.suspect  # type: ignore[union-attr]
    assert outcomes(city, "valve-port-12") == ["no_effect"]
    assert city.g.containment.is_unreliable("valve-port-12")


async def test_untrusted_verify_sensor_gives_unknown_and_quarantine_watch(city: Harness) -> None:
    await _forward(city, call())
    await city.g.containment.isolate("fm-port-01", "zone-07", "test", [])
    await city.advance(35)
    assert outcomes(city, "valve-port-12") == ["unknown"]
    assert not city.g.containment.is_unreliable("valve-port-12")
    await city.g.containment.quarantine("tc-port-01", "sensor", "test", "zone-07")
    await city.advance(15)
    assert outcomes(city, "tc-port-01") == ["verified"]
