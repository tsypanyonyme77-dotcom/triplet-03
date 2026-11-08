"""A reading in the Guardian's contract 1.0 (guardian/INTERFACE.md section 4.1).

Its envelope is `{contract_version: "1.0", sensor_id, sensor_type, zone_id, timestamp, sequence_no, value,
sequence_reset, hmac}`, with no other field, and `value` must hold exactly the fields its sensor registry
lists for the type, so each type is mapped here and a reading of a type it does not know is not sent.
EXTENDED lists the Twin's types its stock registry lacks: they go out only when configured
(GUARDIAN_EXTENDED_TYPES), once the Guardian has registered them with these exact fields.
The sensor id and sequence number are the Twin's own, the same the City Brain reads, because the Brain
asks the Guardian for its verdict by that pair.

HMAC: SHA-256 over the envelope without `hmac`, keys sorted, no whitespace, UTF-8, with TWIN_HMAC_KEY.
Floats are written as Python writes them, which is how the Guardian re-serialises what it receives.

`sequence_reset` is true on the first reading of each sensor this process sends: the Twin's sequence
numbers start again after a restart, and the Guardian accepts the reset because the timestamp is newer.
"""
from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Callable

GUARDIAN_CONTRACT_VERSION = "1.0"
# our emergency call categories in theirs (fire, flood, accident, medical, crime); `other` has no match
INCIDENT_TYPE = {"fire": "fire", "flood": "flood", "medical": "medical", "police": "crime"}


def _traffic_camera(v: dict[str, Any]) -> dict[str, Any]:
    return {"vehicle_count": int(v["vehicle_count"]), "avg_speed_kmh": float(v["avg_speed_kmh"]),
            "congestion_score": float(v["congestion_score"])}


def _air_quality(v: dict[str, Any]) -> dict[str, Any]:
    return {"aqi": float(v["aqi"]), "smoke": bool(v.get("smoke_detected", False))}


def _emergency_call(v: dict[str, Any]) -> dict[str, Any] | None:
    kind = INCIDENT_TYPE.get(v.get("category"))
    if kind is None:
        return None
    return {"call_id": v["call_id"], "incident_type": kind, "caller_id": str(v.get("caller_id") or v["call_id"])}


# our type -> [(their type, sensor id from ours, value from ours)]; one of ours can be two of theirs
MAPPINGS: dict[str, list[tuple[str, Callable[[str], str], Callable[[dict[str, Any]], dict[str, Any] | None]]]] = {
    "traffic_camera": [("traffic_camera", lambda s: s, _traffic_camera)],
    "water_level": [("water_level", lambda s: s, lambda v: {"level_m": float(v["level_m"])}),
                    ("flow_meter", lambda s: "flow-" + s.removeprefix("wl-"), lambda v: {"flow_rate_m3s": float(v["flow_rate_m3s"])})],
    "rainfall": [("rain_gauge", lambda s: s, lambda v: {"rainfall_mm_h": float(v["mm_per_hr"])})],
    "air_quality": [("air_quality", lambda s: s, _air_quality)],
    "emergency_call": [("emergency_call", lambda s: s, _emergency_call)],
}


# sent only when named in GUARDIAN_EXTENDED_TYPES: the Guardian's registry must hold these fields first
EXTENDED: dict[str, list[tuple[str, Callable[[str], str], Callable[[dict[str, Any]], dict[str, Any] | None]]]] = {
    "cctv_anomaly": [("cctv_anomaly", lambda s: s, lambda v: {"anomaly_type": v["anomaly_type"], "confidence": float(v["confidence"])})],
    "building_fire": [("building_fire", lambda s: s, lambda v: {"building_id": v["building_id"], "smoke_detected": bool(v["smoke_detected"]),
                                                                "temp_c": float(v["temp_c"]), "co2_ppm": float(v["co2_ppm"])})],
    "unit_status": [("unit_status", lambda s: s, lambda v: {"unit_id": v["unit_id"], "incident_id": v["incident_id"], "state": v["state"]})],
}


def guardian_hmac(envelope: dict[str, Any], key: str) -> str:
    body = {k: v for k, v in envelope.items() if k != "hmac"}
    payload = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return hmac.new(key.encode(), payload, hashlib.sha256).hexdigest()


class GuardianDialect:
    """Renders the Twin's readings for the Guardian, remembering which sensors it has already sent."""

    def __init__(self, key: str, extended_types: tuple[str, ...] = ()) -> None:
        unknown = set(extended_types) - set(EXTENDED)
        if unknown:
            raise ValueError(f"GUARDIAN_EXTENDED_TYPES: no mapping for {sorted(unknown)}; known: {sorted(EXTENDED)}")
        self.key = key
        self.mappings = {**MAPPINGS, **{t: EXTENDED[t] for t in extended_types}}
        self._sent: set[str] = set()

    def judges(self, reading: dict[str, Any]) -> bool:
        """Whether the Guardian will have a verdict on this reading, under the reading's own id."""
        return any(sensor_id_of(reading["sensor_id"]) == reading["sensor_id"] and value_of(reading["value"]) is not None
                   for _, sensor_id_of, value_of in self.mappings.get(reading["type"], []))

    def render(self, reading: dict[str, Any]) -> list[dict[str, Any]]:
        """The Guardian envelopes for one of our readings (none for a type it does not know)."""
        out = []
        for their_type, sensor_id_of, value_of in self.mappings.get(reading["type"], []):
            value = value_of(reading["value"])
            if value is None:
                continue
            sensor_id = sensor_id_of(reading["sensor_id"])
            envelope = {"contract_version": GUARDIAN_CONTRACT_VERSION, "sensor_id": sensor_id, "sensor_type": their_type,
                        "zone_id": reading["zone_id"], "timestamp": reading["timestamp"], "sequence_no": reading["sequence_no"],
                        "value": value, "sequence_reset": sensor_id not in self._sent}
            envelope["hmac"] = guardian_hmac(envelope, self.key)
            self._sent.add(sensor_id)
            out.append(envelope)
        return out
