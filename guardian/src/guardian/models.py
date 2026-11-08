"""Internal domain models. Wire formats live in adapters/schemas; everything else uses these."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Status(StrEnum):
    trusted = "trusted"
    suspect = "suspect"
    untrusted = "untrusted"
    unknown = "unknown"


class ThreatLevel(StrEnum):
    normal = "normal"
    elevated = "elevated"
    under_attack = "under_attack"

    @property
    def rank(self) -> int:
        return list(ThreatLevel).index(self)


Severity = Literal["info", "low", "medium", "strong", "hard", "impossible"]


class Reading(BaseModel):
    sensor_id: str
    sensor_type: str
    zone_id: str
    ts: datetime
    sequence_no: int
    value: dict[str, Any]
    sequence_reset: bool = False
    source: str = "twin"


class LayerResult(BaseModel):
    layer: str
    passed: bool
    severity: Severity = "info"
    reason_code: str | None = None
    detail: str = ""


class Verdict(BaseModel):
    verdict_id: str
    sensor_id: str
    sequence_no: int | None
    sensor_type: str | None = None
    zone_id: str | None = None
    status: Status
    trust_score: float
    reasons: list[str] = Field(default_factory=list)
    layer_results: list[LayerResult] = Field(default_factory=list)
    action_taken: str | None = None
    threat_level: ThreatLevel = ThreatLevel.normal
    ts: datetime
    expires_at: datetime
    signature: str = ""
    # internal only: detection outcome before containment overrides; used for release counting
    raw_status: Status | None = None
    self_consistent: bool = False
    corroborated: bool = False
    corroborating_sources: int = 0
    notable: bool = False
    value: dict[str, Any] | None = None


class ActuatorCall(BaseModel):
    call_id: str
    actuator_id: str
    action: str
    params: dict[str, Any] = Field(default_factory=dict)
    zone_id: str | None = None
    requesting_layer: str = "brain"
    trust_ref: str | None = None
    justification: str = ""
    incident_id: str | None = None


class Decision(BaseModel):
    call_id: str
    decision: Literal["forwarded", "blocked"]
    reasons: list[str] = Field(default_factory=list)
    twin_reply: dict[str, Any] | None = None


class Alert(BaseModel):
    alert_id: str
    type: str
    zone_id: str | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    suggested_response: str
    threat_level: ThreatLevel = ThreatLevel.normal
    ts: datetime


class AuditEvent(BaseModel):
    event_id: str
    ts: datetime
    type: Literal["reading", "verdict", "decision", "action", "alert", "containment", "error", "system"]
    scenario_id: str | None = None
    sensor_id: str | None = None
    actuator_id: str | None = None
    zone_id: str | None = None
    summary: str
    data: dict[str, Any] = Field(default_factory=dict)


class ContainmentRecord(BaseModel):
    device_id: str
    kind: Literal["isolation", "quarantine", "unreliable"]
    device_type: Literal["sensor", "actuator", "caller"] = "sensor"
    zone_id: str | None = None
    reason: str
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    since: datetime
    cooldown_s: float = 0
    good_readings: int = 0
    active: bool = True


class Signal(BaseModel):
    """A fact the threat correlator consumes (from verdicts, ingest errors, auditor decisions)."""

    type: str
    ts: datetime
    zone_id: str | None = None
    device_id: str | None = None
    source: str | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)
