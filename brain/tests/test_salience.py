"""Salience: a number computed in code from what the Brain can observe, never from a model."""

from datetime import timedelta

from brain.config import WorkspacePolicy
from brain.contracts import Incident
from brain.mind.salience import salience
from tests.conftest import T0

POLICY = WorkspacePolicy()


def incident(world, type, zone, readings, incident_id="inc-0001"):
    found = Incident(incident_id=incident_id, type=type, zone_id=zone, occurred_at=T0, evidence=readings)
    world.store.add_incident(found)
    return found


def score(world, found, others=(), at_s=10, surprise=0.0):
    return salience(found, world.store, list(others), T0 + timedelta(seconds=at_s), POLICY, surprise)


def test_untrusted_evidence_does_not_ignite(world):
    reading = world.reading("wl-01-01", "water_level", "zone-01", {"level_m": 1.3}, 5, status="untrusted")

    value, features = score(world, incident(world, "flood", "zone-01", [reading]))

    assert value == 0.0 and features["trust"] == 0.0


def test_a_trusted_fire_scores_above_a_trusted_jam(world):
    smoke = world.reading("tcam-06-01", "traffic_camera", "zone-06", {"congestion_score": 0.2, "vehicle_count": 3, "avg_speed_kmh": 30.0, "smoke_detected": True}, 5)
    queue = world.reading("tcam-05-01", "traffic_camera", "zone-05", {"congestion_score": 0.9, "vehicle_count": 40, "avg_speed_kmh": 4.0}, 5)

    fire, _ = score(world, incident(world, "fire", "zone-06", [smoke]))
    jam, _ = score(world, incident(world, "jam", "zone-05", [queue], "inc-0002"))

    assert fire > jam


def test_corroboration_raises_the_score(world):
    first = world.reading("wl-01-01", "water_level", "zone-01", {"level_m": 1.3}, 5)
    found = incident(world, "flood", "zone-01", [first])
    alone, _ = score(world, found)

    second = world.reading("call-feed-01", "emergency_call", "zone-01", {"call_id": "c1", "category": "flood"}, 6)
    found.evidence.append(second)
    together, features = score(world, found)

    assert together > alone and features["corroboration"] > 0.3


def test_a_stale_incident_scores_lower_than_a_fresh_one(world):
    reading = world.reading("wl-01-01", "water_level", "zone-01", {"level_m": 1.3}, 5)
    found = incident(world, "flood", "zone-01", [reading])

    fresh, _ = score(world, found, at_s=10)
    stale, _ = score(world, found, at_s=900)

    assert stale < fresh


def test_the_features_are_all_between_zero_and_one(world):
    reading = world.reading("cam-07-02", "cctv_anomaly", "zone-07", {"anomaly_type": "robbery", "confidence": 0.9}, 5)
    other = incident(world, "fire", "zone-07", [reading], "inc-0009")
    found = incident(world, "crime", "zone-07", [reading])

    value, features = score(world, found, others=[other])

    assert 0.0 <= value <= 1.0
    assert set(features) == {"severity", "trust", "corroboration", "novelty", "clustering", "freshness", "surprise", "urgency"}
    assert all(0.0 <= v <= 1.0 for v in features.values())


def test_an_unexpected_reading_makes_an_incident_more_salient(world):
    reading = world.reading("wl-01-01", "water_level", "zone-01", {"level_m": 2.4}, 5)
    found = incident(world, "flood", "zone-01", [reading])

    plain, _ = score(world, found)
    unexpected, features = score(world, found, surprise=1.0)

    assert unexpected > plain and features["surprise"] == 1.0


def test_surprise_cannot_lift_untrusted_evidence_over_the_line(world):
    reading = world.reading("wl-01-01", "water_level", "zone-01", {"level_m": 2.4}, 5, status="untrusted")

    value, _ = score(world, incident(world, "flood", "zone-01", [reading]), surprise=1.0)

    assert value == 0.0


def test_a_verdict_at_the_full_trust_line_counts_fully(world):
    reading = world.reading("wl-01-01", "water_level", "zone-01", {"level_m": 1.3}, 5, confidence=POLICY.trust_full_at)

    _, features = score(world, incident(world, "flood", "zone-01", [reading]))

    assert features["trust"] == 1.0


def test_a_low_confidence_trusted_verdict_counts_less(world):
    reading = world.reading("wl-01-01", "water_level", "zone-01", {"level_m": 1.3}, 5, confidence=POLICY.trust_full_at / 2)

    value, features = score(world, incident(world, "flood", "zone-01", [reading]))
    full = world.reading("wl-01-02", "water_level", "zone-01", {"level_m": 1.3}, 5)
    full_value, _ = score(world, incident(world, "flood", "zone-01", [full], "inc-0002"))

    assert features["trust"] == 0.5
    assert value < full_value


def test_confidence_cannot_lift_an_untrusted_verdict(world):
    reading = world.reading("wl-01-01", "water_level", "zone-01", {"level_m": 1.3}, 5, status="untrusted", confidence=1.0)

    value, features = score(world, incident(world, "flood", "zone-01", [reading]))

    assert value == 0.0 and features["trust"] == 0.0


def test_confidence_is_averaged_over_all_the_evidence(world):
    sure = world.reading("wl-01-01", "water_level", "zone-01", {"level_m": 1.3}, 5)
    unsure = world.reading("call-feed-01", "emergency_call", "zone-01", {"call_id": "c1", "category": "flood"}, 6, confidence=POLICY.trust_full_at / 2)

    _, features = score(world, incident(world, "flood", "zone-01", [sure, unsure]))

    assert features["trust"] == 0.75


def _two_cameras(world):
    first = world.reading("tcam-05-01", "traffic_camera", "zone-05", {"congestion_score": 0.9, "vehicle_count": 40, "avg_speed_kmh": 4.0}, 5)
    second = world.reading("tcam-05-02", "traffic_camera", "zone-05", {"congestion_score": 0.9, "vehicle_count": 38, "avg_speed_kmh": 5.0}, 6)
    return incident(world, "jam", "zone-05", [first, second])


def test_by_default_two_cameras_in_one_zone_are_two_sources(world):
    _, features = score(world, _two_cameras(world))

    assert features["corroboration"] == round(2 / 3, 3)


def test_two_cameras_in_one_zone_are_one_cause(world):
    found = _two_cameras(world)

    _, features = salience(found, world.store, [], T0 + timedelta(seconds=10), WorkspacePolicy(corroboration_by="cause"))

    assert features["corroboration"] == round(1 / 3, 3)


def test_a_camera_and_a_call_are_two_causes(world):
    camera = world.reading("tcam-05-01", "traffic_camera", "zone-05", {"congestion_score": 0.9, "vehicle_count": 40, "avg_speed_kmh": 4.0}, 5)
    call = world.reading("call-feed-01", "emergency_call", "zone-05", {"call_id": "c9", "category": "other"}, 6)

    _, features = salience(incident(world, "jam", "zone-05", [camera, call]), world.store, [], T0 + timedelta(seconds=10),
                           WorkspacePolicy(corroboration_by="cause"))

    assert features["corroboration"] == round(2 / 3, 3)


def test_the_same_type_in_two_zones_is_two_causes(world):
    near = world.reading("tcam-05-01", "traffic_camera", "zone-05", {"congestion_score": 0.9, "vehicle_count": 40, "avg_speed_kmh": 4.0}, 5)
    far = world.reading("tcam-06-01", "traffic_camera", "zone-06", {"congestion_score": 0.9, "vehicle_count": 40, "avg_speed_kmh": 4.0}, 6)

    _, features = salience(incident(world, "jam", "zone-05", [near, far]), world.store, [], T0 + timedelta(seconds=10),
                           WorkspacePolicy(corroboration_by="cause"))

    assert features["corroboration"] == round(2 / 3, 3)


