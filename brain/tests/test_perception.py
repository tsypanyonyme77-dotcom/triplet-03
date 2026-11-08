import pytest

from brain.contracts import CONTRACT_VERSION, AirQuality, PowerLoad, TrafficCamera, WaterLevel
from brain.contracts.signing import sign
from brain.perception import ContractError, Perception
from brain.timeline import JsonlSink, Timeline, verify_chain

SECRET = "test-twin-secret"


def envelope(**overrides):
    base = {
        "contract_version": CONTRACT_VERSION, "sensor_id": "cit-feed-07", "type": "citizen_activity",
        "zone_id": "zone-07", "timestamp": "2026-11-02T14:03:21.000Z", "sequence_no": 1,
        "value": {"citizen_id": "cit-1", "activity": "walking", "speed_kmh": 4.0},
    }
    base.update(overrides)
    return base


@pytest.fixture
def perception():
    return Perception([CONTRACT_VERSION], SECRET)


def test_a_signed_reading_is_accepted_and_typed(perception):
    perceived = perception.ingest(sign(envelope(), SECRET, "twin"))

    assert perceived.reading.reading_id == "cit-feed-07#1"
    assert perceived.value.citizen_id == "cit-1"


def test_fields_outside_the_allowlist_are_dropped_and_reported(perception):
    raw = envelope(value={"citizen_id": "cit-1", "age": 30, "wealth": "low"})

    perceived = perception.ingest(sign(raw, SECRET, "twin"))

    assert perceived.dropped_fields == ["age", "wealth"]
    assert not hasattr(perceived.value, "age")


def test_unknown_reading_types_pass_through_untyped(perception):
    raw = envelope(sensor_id="nl-01", type="noise_level", value={"db": 61})

    assert perception.ingest(sign(raw, SECRET, "twin")).value is None


@pytest.mark.parametrize(
    ("raw", "code", "mentions"),
    [
        ("not an object", "schema_invalid", "JSON object"),
        (envelope(contract_version="2025-01-01"), "bad_contract_version", "2025-01-01"),
        ({k: v for k, v in envelope().items() if k != "zone_id"}, "schema_invalid", "zone_id"),
        (envelope(sequence_no="abc"), "schema_invalid", "sequence_no"),
        (envelope(), "signature_missing", "provenance.hmac"),
        ({**envelope(), "provenance": {"signed_by": "twin", "hmac": "00"}}, "signature_invalid", "does not match"),
        (sign(envelope(value={"activity": "walking"}), SECRET, "twin"), "value_invalid", "citizen_id"),
    ],
)
def test_rejections_name_the_problem(perception, raw, code, mentions):
    with pytest.raises(ContractError) as error:
        perception.ingest(raw)

    assert error.value.code == code
    assert mentions in error.value.message


def test_tampering_after_signing_is_detected(perception):
    raw = sign(envelope(), SECRET, "twin")
    raw["value"]["speed_kmh"] = 40.0

    with pytest.raises(ContractError) as error:
        perception.ingest(raw)
    assert error.value.code == "signature_invalid"


def test_replayed_sequence_numbers_are_rejected(perception):
    perception.ingest(sign(envelope(sequence_no=5), SECRET, "twin"))

    with pytest.raises(ContractError) as error:
        perception.ingest(sign(envelope(sequence_no=5), SECRET, "twin"))
    assert error.value.code == "replay_or_out_of_order"


def test_the_log_hash_chain_detects_edits(tmp_path):
    path = tmp_path / "run.jsonl"
    sink = JsonlSink(path)
    timeline = Timeline([sink])
    for index in range(3):
        timeline.emit("brain.test", "subject", {"index": index})
    sink.close()
    assert verify_chain(path) == (True, "3 records, chain intact")

    lines = path.read_text().splitlines()
    lines[1] = lines[1].replace('"index": 1', '"index": 99')
    path.write_text("\n".join(lines) + "\n")

    ok, message = verify_chain(path)
    assert not ok and "line 2" in message


def test_a_traffic_camera_reading_is_parsed_into_its_typed_value(perception):
    raw = envelope(sensor_id="tcam-05-01", type="traffic_camera", zone_id="zone-05",
                   value={"congestion_score": 0.73, "vehicle_count": 31, "avg_speed_kmh": 12.0})

    perceived = perception.ingest(sign(raw, SECRET, "twin"))

    assert isinstance(perceived.value, TrafficCamera)
    assert perceived.value.congestion_score == 0.73
    assert perceived.value.smoke_detected is False


def test_a_water_level_reading_without_flow_rate_is_accepted(perception):
    raw = envelope(sensor_id="wl-01-01", type="water_level", zone_id="zone-01", value={"level_m": 0.4})

    perceived = perception.ingest(sign(raw, SECRET, "twin"))

    assert isinstance(perceived.value, WaterLevel)
    assert perceived.value.flow_rate_m3s is None


@pytest.mark.parametrize(
    ("type", "value"),
    [
        ("traffic_camera", {"congestion_score": 1.4, "vehicle_count": 3, "avg_speed_kmh": 10.0}),
        ("water_level", {"level_m": -0.2}),
        ("air_quality", {"aqi": 900, "pm25_ugm3": 12.0, "pm10_ugm3": 20.0}),
        ("power_load", {"load_kw": 100.0, "capacity_kw": 0.0, "voltage_v": 230.0}),
    ],
)
def test_out_of_range_sensor_values_are_rejected_with_a_clear_code(perception, type, value):
    raw = envelope(sensor_id="s-1", type=type, value=value)

    with pytest.raises(ContractError) as error:
        perception.ingest(sign(raw, SECRET, "twin"))

    assert error.value.code == "value_invalid"


@pytest.mark.parametrize(
    ("type", "value", "model"),
    [
        ("traffic_camera", {"congestion_score": 0.2, "vehicle_count": 3, "avg_speed_kmh": 30.0}, TrafficCamera),
        ("water_level", {"level_m": 0.4}, WaterLevel),
        ("power_load", {"load_kw": 340.0, "capacity_kw": 500.0, "voltage_v": 229.0}, PowerLoad),
        ("air_quality", {"aqi": 58, "pm25_ugm3": 14.0, "pm10_ugm3": 22.0}, AirQuality),
    ],
)
def test_unknown_extra_fields_on_the_new_types_are_dropped_and_reported(perception, type, value, model):
    raw = envelope(sensor_id="s-1", type=type, value={**value, "operator_name": "someone"})

    perceived = perception.ingest(sign(raw, SECRET, "twin"))

    assert isinstance(perceived.value, model)
    assert perceived.dropped_fields == ["operator_name"]


RIVER = {"water_level": {"level_m": {"from": "depth_cm", "scale": 0.01}}}


def profiled(**kwargs):
    from brain.config import TwinConfig

    twin = TwinConfig.model_validate(kwargs)
    return Perception([CONTRACT_VERSION], SECRET, profiles=twin.profiles, type_aliases=twin.type_aliases)


def water(value, **overrides):
    return sign(envelope(sensor_id="wl-01-01", type="water_level", value=value, **overrides), SECRET, "twin")


def test_without_a_profile_a_renamed_field_is_rejected_with_a_clear_code(perception):
    with pytest.raises(ContractError) as error:
        perception.ingest(water({"depth_cm": 135}))

    assert error.value.code == "value_invalid" and "level_m" in error.value.message


def test_a_renamed_field_is_absorbed_by_a_profile():
    perceived = profiled(profiles=RIVER).ingest(water({"depth_cm": 135, "flow_rate_m3s": 2.0}))

    assert perceived.value.level_m == pytest.approx(1.35)
    assert perceived.dropped_fields == []
    assert perceived.reading.reading_id == "wl-01-01#1"


def test_a_renamed_sensor_type_is_absorbed_by_an_alias():
    twin = profiled(type_aliases={"river_gauge": "water_level"})
    raw = sign(envelope(sensor_id="wl-01-01", type="river_gauge", value={"level_m": 0.4}), SECRET, "twin")

    perceived = twin.ingest(raw)

    assert perceived.reading.type == "water_level" and perceived.value.level_m == 0.4


def test_a_profile_never_overwrites_a_field_the_twin_really_sent():
    perceived = profiled(profiles=RIVER).ingest(water({"level_m": 0.5, "depth_cm": 999}))

    assert perceived.value.level_m == 0.5


def test_a_profiled_value_out_of_range_is_still_rejected():
    with pytest.raises(ContractError) as error:
        profiled(profiles=RIVER).ingest(water({"depth_cm": -20}))

    assert error.value.code == "value_invalid"


def test_a_tampered_reading_is_still_rejected_with_a_profile_in_place():
    raw = water({"depth_cm": 135})
    raw["value"]["depth_cm"] = 900

    with pytest.raises(ContractError) as error:
        profiled(profiles=RIVER).ingest(raw)

    assert error.value.code == "signature_invalid"


def test_a_profile_whose_source_field_is_not_a_number_is_a_value_error_not_a_crash():
    with pytest.raises(ContractError) as error:
        profiled(profiles=RIVER).ingest(water({"depth_cm": "deep"}))

    assert error.value.code == "value_invalid"


def test_the_reading_the_brain_keeps_carries_only_allowlisted_fields(perception):
    raw = envelope(value={"citizen_id": "cit-1", "activity": "walking", "speed_kmh": 4.0, "age": 41, "wealth": "low"})

    perceived = perception.ingest(sign(raw, SECRET, "twin"))

    assert perceived.dropped_fields == ["age", "wealth"]
    assert "age" not in perceived.reading.value and "wealth" not in perceived.reading.value
    assert perceived.reading.value["citizen_id"] == "cit-1"


def test_an_unknown_type_keeps_its_value_as_sent(perception):
    perceived = perception.ingest(sign(envelope(sensor_id="nl-1", type="noise_level", value={"db": 61, "who": "x"}), SECRET, "twin"))

    assert perceived.reading.value == {"db": 61, "who": "x"}


def test_a_reading_stamped_far_from_the_clock_is_refused_when_a_limit_is_set():
    from brain import clock

    now = clock.current().now().isoformat().replace("+00:00", "Z")
    limited = Perception([CONTRACT_VERSION], SECRET, max_age_s=30)

    assert limited.ingest(sign(envelope(timestamp=now), SECRET, "twin")).reading.sequence_no == 1
    for stamp in ("2020-01-01T00:00:00.000Z", "2099-01-01T00:00:00.000Z"):
        with pytest.raises(ContractError) as error:
            limited.ingest(sign(envelope(timestamp=stamp, sequence_no=2), SECRET, "twin"))
        assert error.value.code == "reading_stale"


def test_a_stale_reading_does_not_use_up_its_sequence_number():
    from brain import clock

    limited = Perception([CONTRACT_VERSION], SECRET, max_age_s=30)
    with pytest.raises(ContractError):
        limited.ingest(sign(envelope(timestamp="2020-01-01T00:00:00.000Z", sequence_no=5), SECRET, "twin"))

    now = clock.current().now().isoformat().replace("+00:00", "Z")
    assert limited.ingest(sign(envelope(timestamp=now, sequence_no=5), SECRET, "twin")).reading.sequence_no == 5


def test_without_a_limit_the_timestamp_is_not_compared_with_the_clock(perception):
    assert perception.ingest(sign(envelope(timestamp="2020-01-01T00:00:00.000Z"), SECRET, "twin")).reading.sequence_no == 1
