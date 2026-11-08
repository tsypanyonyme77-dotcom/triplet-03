"""Shared-contract helpers, following the Guardian team's draft data dictionary (docs/data-dictionary.md)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field

from twin.signing import sign

CONTRACT_VERSION = "2026-09-17"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def build_reading(*, sensor_id: str, sensor_type: str, zone_id: str, sequence_no: int,
                  value: dict[str, Any], key: str, department: str | None = None) -> dict[str, Any]:
    reading: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "sensor_id": sensor_id,
        "type": sensor_type,
        "zone_id": zone_id,
        "timestamp": now_iso(),
        "sequence_no": sequence_no,
        "value": value,
    }
    if department:
        reading["department"] = department  # proposed extension: department code
    reading["provenance"] = {"signed_by": "twin", "hmac": sign(reading, key)}
    return reading


class ActuatorCall(BaseModel):
    """Actuator call envelope sent by City Brain or Guardian."""

    contract_version: str
    actuator_id: str = Field(min_length=1)
    action: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)
    requesting_layer: Literal["city_brain", "guardian"]
    justification: str = Field(min_length=1)
    trust_ref: str | None = None
    # optional: a retry with the same key gets the first answer back (marked replayed), nothing runs twice
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)
