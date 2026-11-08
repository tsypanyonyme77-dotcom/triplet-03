"""Triage: which readings open, join and end incidents of each type."""

from datetime import timedelta

from brain.config import Policy
from brain.contracts import CONTRACT_VERSION, SensorReading
from brain.triage import Triage
from tests.conftest import T0


def triage_for(world) -> Triage:
    return Triage(Policy(), world.store)


def sense(world, sensor_id, type, zone_id, value, at_s):
    """Store a trusted reading in the world and return it with its parsed value, the way the runtime hands it to triage."""
    from brain.contracts import VALUE_MODELS

    world.reading(sensor_id, type, zone_id, value, at_s)
    reading = SensorReading(contract_version=CONTRACT_VERSION, sensor_id=sensor_id, type=type, zone_id=zone_id,
                            timestamp=T0 + timedelta(seconds=at_s), sequence_no=world._seq[sensor_id], value=value)
    return reading, VALUE_MODELS[type].model_validate(value)


def water(world, level, at_s, sensor="wl-01-01", zone="zone-01"):
    return sense(world, sensor, "water_level", zone, {"level_m": level}, at_s)


def camera(world, congestion, at_s, smoke=False, sensor="tcam-05-01", zone="zone-05"):
    return sense(world, sensor, "traffic_camera", zone,
                 {"congestion_score": congestion, "vehicle_count": 20, "avg_speed_kmh": 10.0, "smoke_detected": smoke}, at_s)


def call(world, category, at_s, zone="zone-05", sensor="call-feed-05", call_id="call-1"):
    return sense(world, sensor, "emergency_call", zone, {"call_id": call_id, "category": category}, at_s)


def test_a_flood_level_over_the_threshold_opens_a_flood_incident_for_disaster_response(world):
    triage = triage_for(world)

    ids, opened = triage.on_reading(*water(world, 1.2, 10))

    assert opened is not None and ids == [opened.incident_id]
    assert opened.type == "flood" and opened.zone_id == "zone-01"
    assert opened.departments == ["DISASTER"]


def test_a_second_flood_reading_in_the_same_zone_joins_the_open_incident(world):
    triage = triage_for(world)
    first_ids, opened = triage.on_reading(*water(world, 1.2, 10))

    ids, second = triage.on_reading(*water(world, 1.4, 20))

    assert second is None and ids == first_ids
    assert len(triage.incidents) == 1
    assert len(opened.evidence) == 2


def test_a_fire_and_a_jam_in_one_zone_are_two_incidents(world):
    triage = triage_for(world)
    triage.on_reading(*camera(world, 0.9, 10))
    ids, fire = triage.on_reading(*camera(world, 0.3, 12, smoke=True))

    assert fire is not None and fire.type == "fire"
    assert sorted(i.type for i in triage.incidents.values()) == ["fire", "jam"]
    assert ids != [next(i.incident_id for i in triage.incidents.values() if i.type == "jam")]


def test_a_fire_call_and_a_smoke_flag_are_two_pieces_of_evidence_for_one_fire(world):
    triage = triage_for(world)
    _, fire = triage.on_reading(*camera(world, 0.3, 10, smoke=True, zone="zone-06", sensor="tcam-06-01"))

    ids, again = triage.on_reading(*call(world, "fire", 20, zone="zone-06", sensor="call-feed-06"))

    assert again is None and ids == [fire.incident_id]
    assert len(fire.evidence) == 2


def test_congestion_below_the_threshold_opens_nothing(world):
    assert triage_for(world).on_reading(*camera(world, 0.69, 10)) == ([], None)


def test_a_collision_flag_below_minimum_confidence_opens_nothing(world):
    triage = triage_for(world)

    assert triage.on_reading(*sense(world, "cam-05-03", "cctv_anomaly", "zone-05",
                                    {"anomaly_type": "collision", "confidence": 0.3}, 10)) == ([], None)
    _, opened = triage.on_reading(*sense(world, "cam-05-03", "cctv_anomaly", "zone-05",
                                         {"anomaly_type": "collision", "confidence": 0.9}, 20))
    assert opened is not None and opened.type == "accident" and opened.departments == ["MEDICAL"]


def test_a_medical_call_opens_an_accident(world):
    _, opened = triage_for(world).on_reading(*call(world, "medical", 10))

    assert opened is not None and opened.type == "accident"


def test_a_recovery_reading_names_the_incident_it_ends_and_an_untrusted_one_is_the_callers_to_judge(world):
    triage = triage_for(world)
    _, flood = triage.on_reading(*water(world, 1.3, 10))

    assert triage.cleared_by(*water(world, 0.5, 60)) == [flood.incident_id]
    assert triage.cleared_by(*water(world, 0.8, 70)) == []
    assert flood.status == "open"


def test_a_clear_jam_reading_names_the_jam(world):
    triage = triage_for(world)
    _, jam = triage.on_reading(*camera(world, 0.85, 10))

    assert triage.cleared_by(*camera(world, 0.35, 90)) == [jam.incident_id]
    assert triage.cleared_by(*camera(world, 0.5, 91)) == []


def test_crime_triage_is_unchanged(world):
    triage = triage_for(world)

    _, opened = triage.on_reading(*sense(world, "cam-07-02", "cctv_anomaly", "zone-07",
                                         {"anomaly_type": "robbery", "confidence": 0.9}, 10))

    assert opened is not None and opened.type == "crime" and opened.departments == ["POLICE"]


def power(world, load, at_s, capacity=500.0):
    return sense(world, "pm-04-01", "power_load", "zone-04", {"load_kw": load, "capacity_kw": capacity, "voltage_v": 229.0}, at_s)


def air(world, aqi, at_s):
    return sense(world, "aq-02-01", "air_quality", "zone-02", {"aqi": aqi, "pm25_ugm3": 20.0, "pm10_ugm3": 30.0}, at_s)


def test_a_load_near_capacity_opens_an_overload_for_utilities(world):
    triage = triage_for(world)

    _, opened = triage.on_reading(*power(world, 480.0, 10))

    assert opened is not None and opened.type == "overload" and opened.departments == ["UTILITIES"]
    assert triage.cleared_by(*power(world, 450.0, 20)) == []
    assert triage.cleared_by(*power(world, 380.0, 30)) == [opened.incident_id]


def test_power_below_the_overload_ratio_opens_nothing(world):
    assert triage_for(world).on_reading(*power(world, 470.0, 10)) == ([], None)


def test_an_aqi_over_the_threshold_opens_smog_and_a_recovery_closes_it(world):
    triage = triage_for(world)
    assert triage.on_reading(*air(world, 140, 5)) == ([], None)

    _, opened = triage.on_reading(*air(world, 170, 10))

    assert opened is not None and opened.type == "smog" and opened.departments == ["UTILITIES"]
    assert triage.cleared_by(*air(world, 120, 20)) == []
    assert triage.cleared_by(*air(world, 80, 30)) == [opened.incident_id]


def test_triage_reads_its_thresholds_from_the_pack_not_from_code(world):
    from brain.departments import load_manifest

    strict = load_manifest("disaster").model_copy(deep=True)
    strict.detectors[0].when[0].value = 2.0  # a flood only from two metres
    triage = Triage(Policy(), world.store, {"DISASTER": strict})

    assert triage.on_reading(*water(world, 1.3, 10)) == ([], None)
    _, opened = triage.on_reading(*water(world, 2.1, 20))
    assert opened is not None and opened.type == "flood" and opened.departments == ["DISASTER"]


def test_a_reading_of_a_type_no_pack_watches_opens_nothing(world):
    triage = Triage(Policy(), world.store, {})

    assert triage.on_reading(*water(world, 5.0, 10)) == ([], None)


def stalling(world, stall_s=30):
    return Triage(Policy.model_validate({"triage": {"stall_s": stall_s}}), world.store)


def test_an_open_incident_with_no_new_evidence_is_reported_stalled_once(world):
    triage = stalling(world)
    reading, value = water(world, 2.0, 0)
    triage.on_reading(reading, value)

    assert triage.stalled(T0 + timedelta(seconds=29)) == []
    assert [i.type for i in triage.stalled(T0 + timedelta(seconds=31))] == ["flood"]
    assert triage.stalled(T0 + timedelta(seconds=90)) == []


def test_new_evidence_rearms_the_stall(world):
    triage = stalling(world)
    triage.on_reading(*water(world, 2.0, 0))
    triage.stalled(T0 + timedelta(seconds=31))
    triage.on_reading(*water(world, 2.1, 40))

    assert triage.stalled(T0 + timedelta(seconds=60)) == []
    assert len(triage.stalled(T0 + timedelta(seconds=80))) == 1


def test_a_closed_incident_is_never_stalled(world):
    triage = stalling(world)
    _, opened = triage.on_reading(*water(world, 2.0, 0))
    triage.close(opened.incident_id, "cleared")

    assert triage.stalled(T0 + timedelta(seconds=500)) == []


def test_with_stall_off_nothing_is_ever_stalled(world):
    triage = stalling(world, stall_s=0)
    triage.on_reading(*water(world, 2.0, 0))

    assert triage.stalled(T0 + timedelta(seconds=5000)) == []


def test_the_stall_flags_survive_a_restart(world):
    triage = stalling(world)
    triage.on_reading(*water(world, 2.0, 0))
    triage.stalled(T0 + timedelta(seconds=31))
    again = stalling(world)
    again.restore(triage.snapshot())

    assert again.stalled(T0 + timedelta(seconds=90)) == []


def test_a_negative_stall_time_is_refused():
    import pytest

    with pytest.raises(ValueError):
        Policy.model_validate({"triage": {"stall_s": -1}})


def test_an_alarm_no_department_recognises_is_named_once_per_kind_and_zone(world):
    triage = triage_for(world)
    riot = sense(world, "cam-01-01", "cctv_anomaly", "zone-01", {"anomaly_type": "riot", "confidence": 0.9}, 10)

    assert triage.on_reading(*riot) == ([], None)
    assert triage.unrecognised(*riot) == "cctv_anomaly:riot"
    assert triage.unrecognised(*riot) is None


def test_a_known_crime_a_collision_and_a_weak_report_are_not_unrecognised(world):
    triage = triage_for(world)

    robbery = sense(world, "cam-01-01", "cctv_anomaly", "zone-01", {"anomaly_type": "robbery", "confidence": 0.9}, 10)
    weak = sense(world, "cam-01-02", "cctv_anomaly", "zone-01", {"anomaly_type": "riot", "confidence": 0.2}, 11)

    assert triage.unrecognised(*robbery) is None  # a crime: it opens an incident instead
    assert triage.unrecognised(*weak) is None  # under the confidence line
    assert triage.unrecognised(*call(world, "other", 12)) == "emergency_call:other"
