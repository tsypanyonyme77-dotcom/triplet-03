"""Detectors as data: a pack says what reading means an incident, in a few lines of YAML."""

import pytest
from pydantic import ValidationError

from brain.departments.detectors import Condition, Detector, first_match, holds


def cond(field, op, value, of=None):
    return Condition(field=field, op=op, value=value, of=of)


def test_a_condition_compares_a_field_to_a_value():
    assert holds([cond("level_m", ">=", 1.0)], {"level_m": 1.0})
    assert not holds([cond("level_m", ">=", 1.0)], {"level_m": 0.99})
    assert holds([cond("smoke", "==", True)], {"smoke": True})
    assert holds([cond("level_m", "<", 1.0), cond("level_m", ">", 0.5)], {"level_m": 0.7})
    assert not holds([cond("level_m", "<", 1.0), cond("level_m", ">", 0.5)], {"level_m": 0.4})


def test_a_condition_can_compare_a_ratio_of_two_fields():
    near = cond("load_kw", ">=", 0.95, of="capacity_kw")

    assert holds([near], {"load_kw": 480.0, "capacity_kw": 500.0})
    assert not holds([near], {"load_kw": 470.0, "capacity_kw": 500.0})


def test_a_condition_on_a_missing_field_is_false():
    assert not holds([cond("level_m", ">=", 1.0)], {"depth": 3})
    assert not holds([cond("level_m", "==", 0)], {})
    assert not holds([cond("load_kw", ">=", 0.9, of="capacity_kw")], {"load_kw": 5.0})


def test_not_equal_holds_when_the_field_is_missing():
    assert holds([cond("smoke_detected", "!=", True)], {})
    assert holds([cond("smoke_detected", "!=", True)], {"smoke_detected": False})
    assert not holds([cond("smoke_detected", "!=", True)], {"smoke_detected": True})


def test_membership_checks_a_list():
    inside = cond("anomaly_type", "in", ["collision", "accident"])

    assert holds([inside], {"anomaly_type": "collision"})
    assert not holds([inside], {"anomaly_type": "robbery"})


def test_a_zero_capacity_ratio_is_false_not_an_error():
    assert not holds([cond("load_kw", ">=", 0.95, of="capacity_kw")], {"load_kw": 10.0, "capacity_kw": 0})


def test_a_non_numeric_value_in_a_numeric_comparison_is_false_not_an_error():
    assert not holds([cond("level_m", ">=", 1.0)], {"level_m": "deep"})


def test_a_higher_priority_detector_wins_on_the_same_reading():
    smoke = Detector(reading="traffic_camera", incident="fire", priority=10, when=[cond("smoke_detected", "==", True)])
    jam = Detector(reading="traffic_camera", incident="jam", when=[cond("congestion_score", ">=", 0.7)])
    ordered = sorted([("MOBILITY", jam), ("FIRE", smoke)], key=lambda pair: -pair[1].priority)

    code, found = first_match(ordered, "traffic_camera", {"smoke_detected": True, "congestion_score": 0.9})

    assert (code, found.incident) == ("FIRE", "fire")
    assert first_match(ordered, "traffic_camera", {"congestion_score": 0.9})[1].incident == "jam"
    assert first_match(ordered, "water_level", {"congestion_score": 0.9}) is None


def test_unknown_keys_in_a_detector_are_rejected():
    with pytest.raises(ValidationError):
        Detector.model_validate({"reading": "x", "incident": "y", "when": [], "treshold": 3})
    with pytest.raises(ValidationError):
        Condition.model_validate({"field": "a", "op": "~=", "value": 1})


def test_a_detector_with_no_conditions_is_rejected_because_it_would_match_everything():
    with pytest.raises(ValidationError):
        Detector.model_validate({"reading": "x", "incident": "y", "when": []})
