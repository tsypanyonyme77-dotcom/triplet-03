"""L4 dynamics (+ baseline + drift), L5 corroboration, L6 liveness/rate: pass and fail cases."""

from __future__ import annotations

from collections import deque
from typing import Any

from guardian.config import Condition
from guardian.detectors.crosscheck import condition_holds
from guardian.ingest.state_store import HistEntry
from guardian.models import ContainmentRecord, Status, Verdict
from tests.conftest import Harness
from tests.unit.helpers import T0, reading


def _seed(h: Harness, sensor_id: str, stype: str, zone: str, value: dict[str, Any], n: int = 30,
          status: Status = Status.trusted, self_consistent: bool = True) -> None:
    """Pretend a sensor has history, an EWMA and a latest verdict."""
    g = h.g
    for i in range(n):
        r = reading(sensor_id, stype, zone, value, seq=i + 1, dt=i)
        g.state.accept(r, h.clock.now())
        g.state.get(sensor_id).history.append(HistEntry(r.ts, r.value, status))  # type: ignore[union-attr]
        if status == Status.trusted:
            g.state.set_lkg(r)
            g.dynamics.learn(r)
    s = g.state.get(sensor_id)
    assert s is not None
    s.latest_verdict = Verdict(verdict_id=f"v-{sensor_id}", sensor_id=sensor_id, sequence_no=n, status=status,
                               trust_score=1.0, ts=T0, expires_at=T0, zone_id=zone,
                               self_consistent=self_consistent)


def test_l4_rate_zscore_flatline(harness: Harness) -> None:
    g = harness.g
    _seed(harness, "wl-port-03", "water_level", "zone-07", {"level_m": 0.4}, n=10)
    reasons = {r.reason_code for r in g.dynamics.check(reading(value={"level_m": 1.8}, seq=99, dt=12))}
    assert "rate_of_change" in reasons
    assert all(r.passed for r in g.dynamics.check(reading(value={"level_m": 0.401}, seq=99, dt=12)))
    # z-score needs min_history trusted samples
    _seed(harness, "fm-port-01", "flow_meter", "zone-07", {"flow_rate_m3s": 1.2}, n=25)
    res = g.dynamics.check(reading("fm-port-01", "flow_meter", value={"flow_rate_m3s": 1.6}, seq=99, dt=1000))
    assert {r.reason_code for r in res} == {"zscore_outlier"}
    # flatline: 50 identical values including this one
    _seed(harness, "aq-port-01", "air_quality", "zone-07", {"aqi": 42.0, "smoke": False}, n=49)
    res = g.dynamics.check(reading("aq-port-01", "air_quality", value={"aqi": 42.0, "smoke": False}, seq=99, dt=50))
    assert any(r.reason_code == "flatline" for r in res)
    # a dry rain gauge at its floor is not frozen
    _seed(harness, "rg-port-01", "rain_gauge", "zone-07", {"rainfall_mm_h": 0.0}, n=60)
    res = g.dynamics.check(reading("rg-port-01", "rain_gauge", value={"rainfall_mm_h": 0.0}, seq=99, dt=61))
    assert all(r.passed for r in res)
    assert g.dynamics.check(reading("new-sensor"))[0].passed


def test_l4_baseline_and_slow_drift(harness: Harness) -> None:
    g = harness.g
    hour = (T0.hour + 1) % 24
    for i in range(300):
        g.baseline.update("wl-x", "level_m", hour, 0.40 + (0.01 if i % 2 else -0.01))
    assert g.baseline.zscore("wl-x", "level_m", hour, 0.40, 0.0) is not None
    assert g.baseline.zscore("wl-x", "level_m", (hour + 1) % 24, 0.40, 0.0) is None
    _seed(harness, "wl-x", "water_level", "zone-07", {"level_m": 0.4}, n=1)
    res = g.dynamics.check(reading("wl-x", value={"level_m": 0.9}, seq=99, dt=100))
    assert any(r.reason_code == "baseline_deviation" for r in res)
    drift = []
    for _ in range(60):  # sub-threshold, same sign, every time
        drift = g.dynamics.check(reading("wl-x", value={"level_m": 0.425}, seq=99, dt=100))
    assert any(r.reason_code == "slow_drift" for r in drift)
    assert not g.baseline.observe_deviation("wl-x", "level_m", 50.0)  # an event resets the drift window
    g.baseline.freeze("wl-x")
    before = g.baseline.buckets[("wl-x", "level_m", hour)][0]
    g.baseline.update("wl-x", "level_m", hour, 9.0)
    assert g.baseline.buckets[("wl-x", "level_m", hour)][0] == before
    assert g.baseline.export(harness.tmp, T0).exists()


def test_condition_ops() -> None:
    c = Condition
    assert condition_holds(c(field="x", op=">", value=1), {"x": 2}, None)
    assert not condition_holds(c(field="x", op=">", value=1), {}, None)
    assert condition_holds(c(field="x", op="in", value=["fire"]), {"x": "fire"}, None)
    assert condition_holds(c(field="f", op="dev", center=50, value=0.5), {"f": 49.2}, None)
    assert condition_holds(c(field="l", op="jump_pct", value=30), {"l": 140}, {"l": 100})
    assert not condition_holds(c(field="l", op="jump_pct", value=30), {"l": 140}, None)


def test_l5_corroboration(harness: Harness) -> None:
    g, l5 = harness.g, harness.g.pipeline.l5
    flood = reading(value={"level_m": 1.8}, dt=30)
    assert l5.is_notable(flood) and not l5.is_notable(reading(dt=30))
    res, agree = l5.check(flood, claim_event=True)
    assert res[0].reason_code == "insufficient_corroboration" and agree == 0
    for sid, z in (("rg-port-01", "zone-07"), ("rg-res-01", "zone-08")):
        _seed(harness, sid, "rain_gauge", z, {"rainfall_mm_h": 0.0}, n=3)
    _seed(harness, "fm-port-01", "flow_meter", "zone-07", {"flow_rate_m3s": 1.2}, n=3)
    res, agree = l5.check(flood, claim_event=True)
    assert {r.reason_code for r in res} == {"no_rainfall_corroboration", "no_flow_corroboration"}
    assert all(r.severity == "strong" for r in res) and agree == 0
    res, agree = l5.check(reading(dt=30), claim_event=False)
    assert res[0].reason_code == "corroborated" and agree == 3
    # contained or untrusted sources do not vote
    g.containment.records[("fm-port-01", "isolation")] = ContainmentRecord(
        device_id="fm-port-01", kind="isolation", reason="t", since=T0)
    g.state.get("rg-res-01").latest_verdict.status = Status.untrusted  # type: ignore[union-attr]
    res, agree = l5.check(reading(dt=30), claim_event=False)
    assert res[0].reason_code == "insufficient_corroboration" and agree == 1
    # tie: one for, one against
    _seed(harness, "rg-sea-01", "rain_gauge", "zone-12", {"rainfall_mm_h": 20.0}, n=3)
    res, _ = l5.check(reading(dt=30), claim_event=False)
    assert res[0].reason_code == "corroboration_inconclusive"


def test_l5_second_caller(harness: Harness) -> None:
    g, l5 = harness.g, harness.g.pipeline.l5
    calls = g.state.zone_calls.setdefault("zone-07", deque())
    calls.append((T0, "c1", "alice", "fire"))
    calls.append((T0, "c2", "bob", "fire"))
    _seed(harness, "aq-port-01", "air_quality", "zone-07", {"aqi": 260.0, "smoke": True}, n=2)
    call = reading("ec-gw-07", "emergency_call", value={"call_id": "c3", "incident_type": "fire", "caller_id": "carol"})
    res, agree = l5.check(call, claim_event=True)
    assert res[0].reason_code == "corroborated" and agree == 3
    assert l5.rule_key(call) == "emergency_call:fire"


def test_l6_liveness(harness: Harness) -> None:
    g, l6 = harness.g, harness.g.liveness
    call = {"call_id": "c1", "incident_type": "medical", "caller_id": "a"}
    assert l6.check(reading("ec-gw-07", "emergency_call", value=call))[0].passed
    dup = l6.check(reading("ec-gw-07", "emergency_call", value=call))[0]
    assert dup.reason_code == "duplicate_call" and dup.severity == "hard"
    for i in range(2, 7):
        res = l6.check(reading("ec-gw-07", "emergency_call", value={**call, "call_id": f"c{i}"}))
    assert [r.reason_code for r in res] == ["call_flood", "needs_corroboration"]
    # message rate
    for i in range(7):
        g.state.accept(reading(seq=i + 1), harness.clock.now())
    assert l6.check(reading(seq=8))[0].reason_code == "rate_exceeded"
    # staleness
    s = g.state.get("wl-port-03")
    assert s is not None and not l6.is_stale(s)
    harness.clock.advance(11)
    assert [x.sensor_id for x in l6.tick()] == ["wl-port-03"] and s.stale
    assert l6.tick() == []
    ec = g.state.sensor("ec-gw-07", "emergency_call", "zone-07")
    assert l6.interval(ec) is None and not l6.is_stale(ec)
    s.last_seen = None
    assert l6.is_stale(s)  # recovered but not heard from: unknown
