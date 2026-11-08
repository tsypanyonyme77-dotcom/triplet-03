"""Belief that an incident is real: a readable sum of evidence, advisory only."""

import math
from datetime import UTC, datetime
from types import SimpleNamespace

from brain.citygraph import MemoryGraphStore
from brain.contracts import SensorReading, TrustVerdict, VerdictStatus
from brain.engines.belief import belief, calibration


def world(*witnesses):
    """(sensor, zone, confidence, status) -> a store holding those readings and an incident citing them."""
    store, evidence = MemoryGraphStore(), []
    for n, (sensor, zone, confidence, status) in enumerate(witnesses, 1):
        reading = SensorReading(contract_version="2026-09-17", sensor_id=sensor, type="cctv_anomaly", zone_id=zone,
                                timestamp=datetime(2026, 11, 4, 10, 0, n, tzinfo=UTC), sequence_no=n, value={})
        store.add_reading(reading, TrustVerdict(verdict_id=f"v-{n}", reading_ref={"sensor_id": sensor, "sequence_no": n}, status=status, confidence=confidence,
                                                reasons=[], issued_at=reading.timestamp, expires_at=reading.timestamp))
        evidence.append(reading.reading_id)
    return store, SimpleNamespace(type="accident", evidence=evidence)


T = VerdictStatus.TRUSTED


def test_two_independent_trusted_witnesses_raise_belief_above_one_witness():
    one, two = belief(*reversed(world(("cam-1", "z1", 0.9, T)))), belief(*reversed(world(("cam-1", "z1", 0.9, T), ("call-1", "z1", 0.9, T))))

    assert two.p > one.p > 0.4 and two.p < 1.0


def test_two_cameras_in_one_zone_count_as_given_by_the_independence_setting():
    store, incident = world(("cam-1", "z1", 0.9, T), ("cam-2", "z1", 0.9, T))

    assert belief(incident, store, independence="sensor").p > belief(incident, store, independence="zone").p


def test_a_doubted_reading_lowers_belief():
    store, incident = world(("cam-1", "z1", 0.9, T))

    assert belief(incident, store, doubted=lambda r: True).p < 0.4 < belief(incident, store).p


def test_an_untrusted_reading_adds_nothing():
    store, incident = world(("cam-1", "z1", 0.9, VerdictStatus.UNTRUSTED))

    assert belief(incident, store).p == 0.4


def test_the_contributions_sum_to_the_log_odds():
    store, incident = world(("cam-1", "z1", 0.9, T), ("call-1", "z2", 0.7, T))
    result = belief(incident, store)

    assert math.isclose(1 / (1 + math.exp(-result.log_odds)), result.p, abs_tol=1e-3) and len(result.contributions) == 2


def test_the_calibration_table_is_not_wildly_off_for_synthetic_witnesses_and_repeats():
    table = calibration(list(range(0, 10)))

    assert table == calibration(list(range(0, 10)))
    assert all(abs(row["share_real"] - row["mean_belief"]) < 0.25 for row in table if row["n"] >= 30)
