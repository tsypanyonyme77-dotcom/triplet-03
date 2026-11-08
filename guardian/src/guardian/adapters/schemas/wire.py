"""Pydantic wire models and converters between wire and internal models."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, StrictBool, StrictInt, StrictStr

from guardian.clock import iso
from guardian.models import ActuatorCall, Alert, AuditEvent, Decision, Reading, Verdict

CONTRACT_VERSION = "1.0"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Envelope(_Strict):
    contract_version: StrictStr
    sensor_id: StrictStr = Field(min_length=1, max_length=128)
    sensor_type: StrictStr = Field(min_length=1, max_length=64)
    zone_id: StrictStr = Field(min_length=1, max_length=64)
    timestamp: AwareDatetime
    sequence_no: StrictInt = Field(ge=0)
    value: dict[str, Any]
    sequence_reset: StrictBool = False
    hmac: StrictStr = Field(pattern=r"^[0-9a-fA-F]{64}$")

    def to_reading(self, source: str = "twin") -> Reading:
        return Reading(
            sensor_id=self.sensor_id,
            sensor_type=self.sensor_type,
            zone_id=self.zone_id,
            ts=self.timestamp,
            sequence_no=self.sequence_no,
            value=dict(self.value),
            sequence_reset=self.sequence_reset,
            source=source,
        )


class ReadingRef(_Strict):
    sensor_id: str
    sequence_no: int | None


class LayerResultOut(_Strict):
    layer: str
    passed: bool
    severity: str = "info"
    reason_code: str | None = None
    detail: str = ""


class VerdictOut(_Strict):
    verdict_id: str
    reading_ref: ReadingRef
    status: Literal["trusted", "suspect", "untrusted", "unknown"]
    trust_score: float = Field(ge=0, le=1)
    reasons: list[str]
    layer_results: list[LayerResultOut]
    action_taken: str | None
    threat_level: Literal["normal", "elevated", "under_attack"]
    ts: str
    expires_at: str
    signature: str

    @classmethod
    def from_verdict(cls, v: Verdict) -> VerdictOut:
        return cls(**verdict_payload(v), signature=v.signature)


def verdict_payload(v: Verdict) -> dict[str, Any]:
    """The signed part of a verdict, exactly as it appears on the wire (minus `signature`)."""
    return {
        "verdict_id": v.verdict_id,
        "reading_ref": {"sensor_id": v.sensor_id, "sequence_no": v.sequence_no},
        "status": v.status.value,
        "trust_score": v.trust_score,
        "reasons": list(v.reasons),
        "layer_results": [lr.model_dump() for lr in v.layer_results],
        "action_taken": v.action_taken,
        "threat_level": v.threat_level.value,
        "ts": iso(v.ts),
        "expires_at": iso(v.expires_at),
    }


class VerdictRequest(_Strict):
    sensor_id: StrictStr = Field(min_length=1)
    sequence_no: StrictInt | None = None


class ActuatorCallIn(_Strict):
    call_id: StrictStr = Field(min_length=1, max_length=128)
    actuator_id: StrictStr = Field(min_length=1, max_length=128)
    action: Literal[
        "set_valve_state", "set_grid_state", "set_signal", "dispatch_unit",
        "quarantine_device", "isolate_sensor", "clear_quarantine",
    ]
    params: dict[str, Any] = Field(default_factory=dict)
    zone_id: StrictStr | None = None
    requesting_layer: StrictStr = "brain"
    trust_ref: StrictStr | None = None
    justification: StrictStr = ""
    incident_id: StrictStr | None = None

    def to_call(self) -> ActuatorCall:
        return ActuatorCall(**self.model_dump())

    @classmethod
    def from_call(cls, c: ActuatorCall) -> ActuatorCallIn:
        return cls.model_validate(c.model_dump())


class TwinReply(BaseModel):
    model_config = ConfigDict(extra="allow")
    status: Literal["ok", "rejected"]
    current_state: dict[str, Any] = Field(default_factory=dict)
    reverts_at: str | None = None


class DecisionOut(_Strict):
    call_id: str
    decision: Literal["forwarded", "blocked"]
    reasons: list[str]
    twin_reply: dict[str, Any] | None

    @classmethod
    def from_decision(cls, d: Decision) -> DecisionOut:
        return cls(**d.model_dump())


class AlertOut(_Strict):
    alert_id: str
    type: str
    zone_id: str | None
    evidence: list[dict[str, Any]]
    suggested_response: str
    threat_level: Literal["normal", "elevated", "under_attack"]
    ts: str

    @classmethod
    def from_alert(cls, a: Alert) -> AlertOut:
        return cls(**{**a.model_dump(mode="json"), "ts": iso(a.ts)})


class AuditEventOut(_Strict):
    event_id: str
    ts: str
    type: Literal["reading", "verdict", "decision", "action", "alert", "containment", "error", "system"]
    scenario_id: str | None
    sensor_id: str | None
    actuator_id: str | None
    zone_id: str | None
    summary: str
    data: dict[str, Any]

    @classmethod
    def from_event(cls, e: AuditEvent) -> AuditEventOut:
        return cls(**{**e.model_dump(mode="json"), "ts": iso(e.ts)})


class ErrorOut(_Strict):
    error: str
    message: str
    field: str | None = None


class ClearRequest(_Strict):
    device_id: StrictStr = Field(min_length=1)
    reason: StrictStr = Field(min_length=1)


class QuarantineRequest(_Strict):
    device_id: StrictStr = Field(min_length=1)
    device_type: Literal["sensor", "actuator", "caller"]
    reason: StrictStr = Field(min_length=1)
    zone_id: StrictStr | None = None

