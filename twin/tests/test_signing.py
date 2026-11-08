from twin.contract import build_reading
from twin.signing import canonical, sign, verify

KEY = "k"


def make():
    return build_reading(sensor_id="ecall-zone-03", sensor_type="emergency_call", zone_id="zone-03",
                         sequence_no=1, value={"call_id": "call-0001"}, key=KEY, department="medical")


def test_reading_has_contract_envelope():
    r = make()
    for field in ("contract_version", "sensor_id", "type", "zone_id", "timestamp", "sequence_no", "value", "provenance"):
        assert field in r
    assert r["provenance"]["signed_by"] == "twin"
    assert r["timestamp"].endswith("Z")


def test_verify_roundtrip_and_tamper():
    r = make()
    assert verify(r, KEY)
    r["value"]["call_id"] = "call-9999"
    assert not verify(r, KEY)


def test_wrong_key_fails():
    assert not verify(make(), "other")


def test_canonical_ignores_provenance_and_key_order():
    a = {"b": 1, "a": 2, "provenance": {"hmac": "x"}}
    b = {"a": 2, "b": 1}
    assert canonical(a) == canonical(b)
    assert sign(a, KEY) == sign(b, KEY)
