"""Hypothesis fuzzing of the envelope parser and POST /v1/readings: malformed input → clean 4xx error model,
never a 500, never a trusted verdict."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from starlette.testclient import TestClient

from guardian.config import load_config
from guardian.ingest.validator import IngestError, validate_envelope
from mocks.common.signing import sign_envelope
from tests.conftest import CONFIG_DIR, TWIN_API, TWIN_KEY, Harness, make_settings

json_values = st.recursive(
    st.none() | st.booleans() | st.integers() | st.floats(allow_nan=False, allow_infinity=False) | st.text(max_size=20),
    lambda children: st.lists(children, max_size=4) | st.dictionaries(st.text(max_size=10), children, max_size=4),
    max_leaves=12,
)
FIELDS = ["contract_version", "sensor_id", "sensor_type", "zone_id", "timestamp", "sequence_no", "value",
          "sequence_reset", "hmac"]
envelope_like = st.fixed_dictionaries({}, optional={f: json_values for f in FIELDS}) | st.fixed_dictionaries({
    "contract_version": st.just("1.0"), "sensor_id": st.text(min_size=1, max_size=10),
    "sensor_type": st.sampled_from(["water_level", "power_meter", "emergency_call", "toaster"]),
    "zone_id": st.sampled_from(["zone-07", "zone-99"]), "timestamp": st.just("2026-11-02T14:00:00Z"),
    "sequence_no": st.integers(min_value=-5, max_value=10**12), "value": json_values,
})
REGISTRY = load_config(CONFIG_DIR, make_settings(Path("/tmp"))).sensors


@settings(max_examples=300, deadline=None)
@given(raw=json_values | envelope_like)
def test_envelope_parser_never_crashes(raw: Any) -> None:
    try:
        validate_envelope(raw, REGISTRY, "1.0")
    except IngestError as e:
        assert e.code in {"schema_invalid", "contract_version_mismatch"} and e.message


_client: dict[str, TestClient] = {}


def client(tmp_path_factory: Any) -> TestClient:
    if "c" not in _client:
        _client["c"] = TestClient(Harness(tmp_path_factory.mktemp("fuzz")).app)
    return _client["c"]


@settings(max_examples=150, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(raw=json_values | envelope_like, signed=st.booleans())
def test_post_readings_fuzz(tmp_path_factory: Any, raw: Any, signed: bool) -> None:
    if signed and isinstance(raw, dict):
        raw = sign_envelope(raw, TWIN_KEY)  # well-signed garbage must still be rejected cleanly
    r = client(tmp_path_factory).post("/v1/readings", json=raw, headers={"X-API-Key": TWIN_API})
    assert r.status_code < 500, r.text
    body = r.json()
    if r.status_code >= 400:
        assert set(body) == {"error", "message", "field"}
    else:
        for item in body["results"]:
            assert "verdict" in item or set(item["error"]) == {"error", "message", "field"}
            if "verdict" in item:
                assert item["verdict"]["status"] != "trusted" or signed
