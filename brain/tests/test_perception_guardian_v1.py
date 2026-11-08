"""Readings in the Guardian team's contract 1.0, as their Twin mock really sent them (captured 8 Nov 2026) and as their Interface Card shows them."""
import copy

import pytest

from brain.adapters.guardian_v1 import sign
from brain.perception import ContractError, Perception

KEY = "dev-twin-hmac"  # the key their Twin mock was started with
SENT = {"contract_version": "1.0", "sensor_id": "wl-port-03", "sensor_type": "water_level", "zone_id": "zone-07", "timestamp": "2026-11-08T15:11:18.510Z",
        "sequence_no": 1, "value": {"level_m": 0.4034}, "sequence_reset": True, "hmac": "8cfb5e3f1b2a46a619972041c2340002d473348694a83757aea597eda076741f"}
CARD = {"contract_version": "1.0", "sensor_id": "wl-port-03", "sensor_type": "water_level", "sequence_no": 4821, "sequence_reset": False,
        "timestamp": "2026-11-02T14:03:18Z", "value": {"level_m": 1.8}, "zone_id": "zone-07", "hmac": "30d230a2d99a160d20260477e151fa91c58e98d6d76875d0d7fffcdc1195911a"}


def perception(**kw) -> Perception:
    return Perception(["2026-09-17"], KEY, True, dialect="guardian-v1", **kw)


def resign(reading: dict) -> dict:
    body = {k: v for k, v in reading.items() if k != "hmac"}
    return {**body, "hmac": sign(body, KEY)}


def test_a_reading_their_twin_really_sent_is_accepted_and_typed():
    seen = perception().ingest(SENT)

    assert seen.reading.type == "water_level" and seen.reading.sensor_id == "wl-port-03" and seen.value.level_m == 0.4034


def test_the_example_in_their_card_verifies_with_its_example_key():
    assert Perception(["2026-09-17"], "example-twin-key", True, dialect="guardian-v1").ingest(CARD).reading.sequence_no == 4821


def test_a_changed_value_or_a_missing_signature_is_refused():
    tampered = copy.deepcopy(SENT)
    tampered["value"]["level_m"] = 9.9
    unsigned = {k: v for k, v in SENT.items() if k != "hmac"}

    with pytest.raises(ContractError) as bad:
        perception().ingest(tampered)
    with pytest.raises(ContractError) as missing:
        perception().ingest(unsigned)

    assert (bad.value.code, missing.value.code) == ("signature_invalid", "signature_missing")


def test_a_reading_in_our_own_format_is_refused_by_a_brain_set_to_their_dialect():
    with pytest.raises(ContractError) as error:
        perception().ingest({k: v for k, v in SENT.items() if k != "sensor_type"})

    assert error.value.code == "schema_invalid" and "sensor_type" in error.value.message


def test_a_repeated_sequence_number_is_a_replay():
    p = perception()
    p.ingest(SENT)

    with pytest.raises(ContractError) as error:
        p.ingest(SENT)

    assert error.value.code == "replay_or_out_of_order"


def test_a_restarted_twin_may_start_the_counter_again_only_with_a_newer_reading():
    p = perception()
    p.ingest(resign({**CARD, "timestamp": "2026-11-08T15:00:00Z", "sequence_no": 50}))
    newer = resign({**SENT, "timestamp": "2026-11-08T15:10:00Z", "sequence_no": 1, "sequence_reset": True})
    older = resign({**SENT, "timestamp": "2026-11-08T14:00:00Z", "sequence_no": 1, "sequence_reset": True})

    with pytest.raises(ContractError, match="not greater"):
        p.ingest(older)
    assert p.ingest(newer).reading.sequence_no == 1


def test_a_sensor_the_brain_does_not_model_passes_untyped_and_an_emergency_call_gets_our_category():
    p = perception()
    rain = p.ingest(resign({**SENT, "sensor_id": "rg-port-01", "sensor_type": "rain_gauge", "value": {"rainfall_mm_h": 3.0}}))
    call = p.ingest(resign({**SENT, "sensor_id": "ec-1", "sensor_type": "emergency_call", "value": {"call_id": "c-1", "incident_type": "crime", "caller_id": "someone"}}))

    assert rain.value is None and rain.reading.type == "rain_gauge"
    assert call.value.category == "police" and "caller_id" not in call.reading.value


def test_our_own_dialect_is_unchanged():
    ours = Perception(["2026-09-17"], KEY, True)

    with pytest.raises(ContractError) as error:
        ours.ingest(SENT)

    assert error.value.code == "bad_contract_version"


def test_their_air_quality_with_a_decimal_aqi_and_no_particulates_is_accepted():
    reading = resign({**SENT, "sensor_id": "aq-port-01", "sensor_type": "air_quality", "value": {"aqi": 42.5, "smoke": False}})

    seen = perception().ingest(reading)

    assert seen.reading.type == "air_quality" and seen.value.aqi == 42.5 and seen.value.pm25_ugm3 is None


def test_their_power_meter_is_our_power_load_without_a_voltage_once_aliased():
    reading = resign({**SENT, "sensor_id": "pm-port-01", "sensor_type": "power_meter", "value": {"load_kw": 360.0, "capacity_kw": 800.0}})

    seen = perception(type_aliases={"power_meter": "power_load"}).ingest(reading)

    assert seen.reading.type == "power_load" and seen.value.load_kw == 360.0 and seen.value.voltage_v is None
