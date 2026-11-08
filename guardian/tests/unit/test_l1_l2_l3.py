"""L1 authenticity, L2 freshness, L3a plausibility, L3b semantic plausibility: pass and fail cases."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from guardian.detectors.authenticity import AuthenticityDetector
from guardian.detectors.freshness import FreshnessDetector
from guardian.detectors.plausibility import PlausibilityDetector
from guardian.detectors.semantic_plausibility import SemanticDetector
from guardian.ingest.validator import IngestError
from guardian.models import ActuatorCall
from guardian.trust.signer import Signer
from tests.conftest import TWIN_KEY, Harness
from tests.unit.helpers import reading


@pytest.fixture
def l1(harness: Harness) -> AuthenticityDetector:
    return AuthenticityDetector(harness.g.cfg.sensors, "1.0", Signer(TWIN_KEY))


def test_l1_valid(l1: AuthenticityDetector, envelope: Callable[..., dict[str, Any]]) -> None:
    env, res = l1.check_raw(envelope())
    assert res.passed and env.sensor_id == "wl-port-03"


def test_l1_bad_hmac(l1: AuthenticityDetector, envelope: Callable[..., dict[str, Any]]) -> None:
    _, res = l1.check_raw(envelope(key="wrong"))
    assert not res.passed and res.severity == "hard" and res.reason_code == "hmac_invalid"
    tampered = envelope()
    tampered["value"] = {"level_m": 1.8}
    assert l1.check_raw(tampered)[1].reason_code == "hmac_invalid"


@pytest.mark.parametrize(("mutate", "code", "field"), [
    (lambda e: e.update(contract_version="2.0"), "contract_version_mismatch", "contract_version"),
    (lambda e: e.pop("contract_version"), "schema_invalid", "contract_version"),
    (lambda e: e.pop("sensor_id"), "schema_invalid", "sensor_id"),
    (lambda e: e.update(sequence_no="7"), "schema_invalid", "sequence_no"),
    (lambda e: e.update(sequence_no=-1), "schema_invalid", "sequence_no"),
    (lambda e: e.update(timestamp="yesterday"), "schema_invalid", "timestamp"),
    (lambda e: e.update(timestamp="2026-11-02T14:00:00"), "schema_invalid", "timestamp"),
    (lambda e: e.update(sensor_type="toaster"), "schema_invalid", "sensor_type"),
    (lambda e: e.update(value={"level_m": "high"}), "schema_invalid", "value.level_m"),
    (lambda e: e.update(value={"level_m": True}), "schema_invalid", "value.level_m"),
    (lambda e: e.update(value={}), "schema_invalid", "value.level_m"),
    (lambda e: e.update(value={"level_m": 1, "extra": 2}), "schema_invalid", "value.extra"),
    (lambda e: e.update(surprise=1), "schema_invalid", "surprise"),
    (lambda e: e.update(hmac="nothex"), "schema_invalid", "hmac"),
])
def test_l1_schema_errors(l1: AuthenticityDetector, envelope: Callable[..., dict[str, Any]],
                          mutate: Callable[[dict[str, Any]], Any], code: str, field: str) -> None:
    e = envelope()
    mutate(e)
    with pytest.raises(IngestError) as info:
        l1.check_raw(e)
    assert info.value.code == code and info.value.field == field


def test_l1_enum_and_non_object(l1: AuthenticityDetector, envelope: Callable[..., dict[str, Any]]) -> None:
    call = envelope(sensor_id="ec-gw-07", sensor_type="emergency_call",
                    value={"call_id": "c1", "incident_type": "alien", "caller_id": "x"})
    with pytest.raises(IngestError, match="one of"):
        l1.check_raw(call)
    with pytest.raises(IngestError, match="JSON object"):
        l1.check_raw([1, 2])


def test_l2_freshness(harness: Harness) -> None:
    g = harness.g
    l2 = FreshnessDetector(g.state, harness.clock, 30)
    r = reading(seq=5)
    assert l2.check(r)[0].passed
    g.state.accept(r, harness.clock.now())
    replay = l2.check(reading(seq=5))[0]
    assert not replay.passed and replay.reason_code == "replay" and replay.severity == "hard"
    assert l2.check(reading(seq=4))[0].reason_code == "replay"
    assert l2.check(reading(seq=6, dt=1))[0].passed
    skew = l2.check(reading(seq=6, dt=31))[0]
    assert skew.reason_code == "timestamp_skew"
    reset = l2.check(reading(seq=1, dt=1, sequence_reset=True))[0]
    assert reset.passed and reset.reason_code == "sequence_reset"
    old_reset = l2.check(reading(seq=1, dt=-1, sequence_reset=True))[0]
    assert old_reset.reason_code == "replay"


@pytest.mark.parametrize(("stype", "value", "reason"), [
    ("water_level", {"level_m": 0.4}, None),
    ("water_level", {"level_m": 180.0}, "unit_mismatch"),
    ("water_level", {"level_m": -1.0}, "out_of_range"),
    ("air_quality", {"aqi": 900.0, "smoke": False}, "out_of_range"),
    ("power_meter", {"load_kw": 620.0, "capacity_kw": 500.0}, "inconsistent"),
    ("traffic_camera", {"vehicle_count": -3, "avg_speed_kmh": 30.0, "congestion_score": 0.5}, "out_of_range"),
    ("traffic_camera", {"vehicle_count": 3, "avg_speed_kmh": 30.0, "congestion_score": 1.7}, "out_of_range"),
    ("grid_meter", {"frequency_hz": 50.0, "voltage_v": 230.0}, None),
])
def test_l3a(harness: Harness, stype: str, value: dict[str, Any], reason: str | None) -> None:
    res = PlausibilityDetector(harness.g.cfg.thresholds).check(reading(sensor_type=stype, value=value))
    if reason is None:
        assert all(r.passed for r in res)
    else:
        assert any(r.reason_code == reason and r.severity == "strong" for r in res)


@pytest.mark.parametrize(("stype", "zone", "value", "reason", "severity"), [
    ("emergency_call", "zone-12", {"call_id": "1", "incident_type": "fire", "caller_id": "a"},
     "impossible_location", "impossible"),
    ("emergency_call", "zone-07", {"call_id": "1", "incident_type": "fire", "caller_id": "a"}, None, None),
    ("emergency_call", "zone-03", {"call_id": "1", "incident_type": "flood", "caller_id": "a"},
     "sensor_environment_mismatch", "medium"),
    ("water_level", "zone-03", {"level_m": 0.3}, "sensor_environment_mismatch", "medium"),
    ("water_level", "zone-07", {"level_m": 3.5}, "physical_coupling", "medium"),
    ("air_quality", "zone-12", {"aqi": 40.0, "smoke": True}, "location_sanity", "medium"),
    ("traffic_camera", "zone-12", {"vehicle_count": 80, "avg_speed_kmh": 30.0, "congestion_score": 0.2},
     "sensor_environment_mismatch", "medium"),
    ("water_level", "zone-99", {"level_m": 0.3}, "unknown_zone", "medium"),
])
def test_l3b(harness: Harness, stype: str, zone: str, value: dict[str, Any], reason: str | None,
             severity: str | None) -> None:
    res = SemanticDetector(harness.g.cfg.city).check(reading(sensor_type=stype, zone_id=zone, value=value))
    if reason is None:
        assert all(r.passed for r in res)
    else:
        assert any(r.reason_code == reason and r.severity == severity for r in res)


def test_l3b_time_context_and_capability(harness: Harness) -> None:
    sem = SemanticDetector(harness.g.cfg.city)
    jam = {"vehicle_count": 100, "avg_speed_kmh": 10.0, "congestion_score": 0.95}
    night = reading(sensor_type="traffic_camera", value=jam, ts=reading().ts.replace(hour=2))  # 03:00 local
    assert any(r.reason_code == "implausible_time_context" for r in sem.check(night))
    assert all(r.passed for r in sem.check(reading(sensor_type="traffic_camera", value=jam)))
    grid = ActuatorCall(call_id="c", actuator_id="g", action="set_grid_state")
    assert sem.action_capability(grid, "zone-12") == "no_switchable_grid"
    assert sem.action_capability(grid, "zone-07") is None
    disp = ActuatorCall(call_id="c", actuator_id="d", action="dispatch_unit")
    assert sem.action_capability(disp, "zone-12") == "no_road_access"
    assert sem.action_capability(disp, None) is None
