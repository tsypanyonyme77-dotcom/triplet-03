"""Canonical message models for the City Brain layer.

The first half mirrors the shared Data Dictionary (what crosses a layer boundary).
The second half is Brain-internal (what the pipeline passes between its own stages).
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from brain import clock

CONTRACT_VERSION = "2026-09-17"


def utcnow() -> datetime:
    return clock.current().now()


# --------------------------------------------------------------------------- shared contract


SAFE_ID = r"^[A-Za-z0-9._:#-]{1,64}$"
Safe = Annotated[str, Field(pattern=SAFE_ID)]  # a short word or id: no spaces, no punctuation that could read as an instruction


class Provenance(BaseModel):
    signed_by: str
    hmac: str  # the signature (hex), whatever the algorithm
    kid: str | None = None  # which key signed; absent means the peer's current key
    alg: Literal["HS256", "EdDSA"] | None = None


class ReadingRef(BaseModel):
    sensor_id: str
    sequence_no: int

    @property
    def reading_id(self) -> str:
        return f"{self.sensor_id}#{self.sequence_no}"


class VerdictStatus(StrEnum):
    TRUSTED = "trusted"
    SUSPICIOUS = "suspicious"
    UNTRUSTED = "untrusted"
    # Brain-internal: the Guardian did not answer within the deadline.
    UNAVAILABLE = "unavailable"


class TrustVerdict(BaseModel):
    """Guardian's answer to "is this reading telling the truth?" (agreed format)."""

    model_config = ConfigDict(extra="allow")

    verdict_id: str
    reading_ref: ReadingRef
    status: VerdictStatus
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    reasons: list[str] = Field(default_factory=list)
    issued_at: AwareDatetime
    expires_at: AwareDatetime | None = None


class SensorReading(BaseModel):
    """Common envelope carried by every sensor reading (Data Dictionary section 1)."""

    model_config = ConfigDict(extra="allow")

    contract_version: str
    # Ids end up in prompts, graph queries and file names: letters, digits and . _ : # - only, so an id cannot carry an instruction.
    sensor_id: str = Field(pattern=SAFE_ID)
    type: str = Field(pattern=SAFE_ID)
    zone_id: str = Field(pattern=SAFE_ID)
    timestamp: AwareDatetime
    sequence_no: int = Field(ge=0)
    value: dict[str, Any]
    provenance: Provenance | None = None
    department_code: str | None = None
    # Present only when the Guardian sits inline and annotates readings itself.
    trust: TrustVerdict | None = None

    @property
    def reading_id(self) -> str:
        return f"{self.sensor_id}#{self.sequence_no}"


class _Value(BaseModel):
    # Fields outside the allowlist are dropped here and never reach scoring or an LLM.
    model_config = ConfigDict(extra="ignore")


class CitizenActivity(_Value):
    """Extension: one observation of one citizen."""

    citizen_id: Safe
    zone_id: Safe | None = None
    node_id: Safe | None = None
    activity: Safe = "unknown"
    speed_kmh: float = Field(default=0.0, ge=0.0)
    heading_zone_id: Safe | None = None
    flags: list[Safe] = Field(default_factory=list)


class CctvAnomaly(_Value):
    anomaly_type: Safe
    confidence: float = Field(ge=0.0, le=1.0)
    # Extension: the entity the camera identified, when it can.
    entity_id: Safe | None = None


class Gunshot(_Value):
    detected: bool
    confidence: float = Field(ge=0.0, le=1.0)


class EmergencyCall(_Value):
    call_id: Safe
    category: Literal["fire", "medical", "police", "flood", "other"]
    caller_confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class UnitStatus(_Value):
    """Extension: feedback on a dispatched unit, so incidents can close."""

    unit_id: Safe
    incident_id: Safe
    # `on_scene` answers a `respond` dispatch; `returning` answers a recall.
    state: Literal["en_route", "pursuing", "in_position", "on_scene", "apprehended", "lost", "returning"]


class TrafficCamera(_Value):
    """Data Dictionary section 2: congestion and, when the camera sees it, smoke."""

    congestion_score: float = Field(ge=0.0, le=1.0)
    vehicle_count: int = Field(ge=0)
    avg_speed_kmh: float = Field(ge=0.0)
    smoke_detected: bool = False


class WaterLevel(_Value):
    level_m: float = Field(ge=0.0)
    flow_rate_m3s: float | None = None


class PowerLoad(_Value):
    load_kw: float = Field(ge=0.0)
    capacity_kw: float = Field(gt=0.0)
    voltage_v: float = Field(ge=0.0)


class AirQuality(_Value):
    aqi: int = Field(ge=0, le=500)
    pm25_ugm3: float = Field(ge=0.0)
    pm10_ugm3: float = Field(ge=0.0)


VALUE_MODELS: dict[str, type[_Value]] = {
    "citizen_activity": CitizenActivity,
    "cctv_anomaly": CctvAnomaly,
    "gunshot": Gunshot,
    "emergency_call": EmergencyCall,
    "unit_status": UnitStatus,
    "traffic_camera": TrafficCamera,
    "water_level": WaterLevel,
    "power_load": PowerLoad,
    "air_quality": AirQuality,
}


class ActuatorCall(BaseModel):
    """Common envelope carried by every actuator call (Data Dictionary section 1)."""

    contract_version: str = CONTRACT_VERSION
    actuator_id: str
    action: str
    params: dict[str, Any]
    requesting_layer: Literal["city_brain", "guardian"] = "city_brain"
    justification: str
    trust_ref: str | None
    # Extensions: the caller signs its calls the way the Twin signs readings, and says when and with a one-time number, so a captured call cannot be replayed.
    issued_at: AwareDatetime | None = None
    nonce: str | None = None
    provenance: Provenance | None = None


class DispatchUnitParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit_type: Literal["police", "ambulance", "fire"]
    zone_id: str
    incident_id: str
    # Extensions for the pursuit scenario. `contain` holds a perimeter zone.
    mode: Literal["respond", "pursuit", "contain", "patrol"] | None = None
    target_id: str | None = None


class BroadcastAlertParams(BaseModel):
    """Data Dictionary section 5 (extended actuators)."""

    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=280)
    channel: Literal["sms", "siren", "app"]
    zone_id: str


class RecallUnitParams(BaseModel):
    """Extension: stand a dispatched unit down and return it to its station."""

    model_config = ConfigDict(extra="forbid")

    unit_id: str
    incident_id: str


class SetSignalPhaseParams(BaseModel):
    """Data Dictionary section 4: hold a traffic signal in one phase for a while."""

    model_config = ConfigDict(extra="forbid")

    intersection_id: str
    phase: Literal["green", "red", "yellow", "flashing"]
    duration_s: int = Field(ge=1, le=3600)


class SetValveStateParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    valve_id: str
    state: Literal["open", "closed"]
    flow_target_pct: float | None = Field(default=None, ge=0.0, le=100.0)


class SetGridConnectionParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    zone_id: str
    state: Literal["connected", "disconnected"]


PARAM_MODELS: dict[str, type[BaseModel]] = {
    "dispatch_unit": DispatchUnitParams,
    "broadcast_alert": BroadcastAlertParams,
    "recall_unit": RecallUnitParams,
    "set_signal_phase": SetSignalPhaseParams,
    "set_valve_state": SetValveStateParams,
    "set_grid_connection": SetGridConnectionParams,
}


class ActuatorResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str
    reason: str | None = None


# --------------------------------------------------------------------------- brain-internal


class Incident(BaseModel):
    incident_id: str
    type: str
    zone_id: str
    occurred_at: AwareDatetime
    status: Literal["open", "closed"] = "open"
    evidence: list[str] = Field(default_factory=list)  # reading ids
    departments: list[str] = Field(default_factory=list)
    outcome: str | None = None


class FeatureHit(BaseModel):
    name: str
    x: float
    weight: float
    trust: float
    reading_ids: list[str] = Field(default_factory=list)
    note: str = ""


class Assessment(BaseModel):
    """How strongly the evidence ties one entity to one incident."""

    incident_id: str
    entity_id: str
    score: float  # trust-weighted
    raw_score: float  # what the data says if every reading were believed
    level: Literal["none", "poi", "suspect"]
    features: list[FeatureHit]
    evidence_reading_ids: list[str]
    trusted_sources: list[str]
    direct_reading_id: str | None = None
    last_zone_id: str | None = None
    heading_zone_id: str | None = None  # where the last sighting says they were heading
    discounted: list[dict[str, str]] = Field(default_factory=list)
    # The rest of the scene: flight only singles someone out when nobody else fled.
    fled_with: list[str] = Field(default_factory=list)  # others at the scene who also left fast
    unaccounted: list[str] = Field(default_factory=list)  # others at the scene not seen since the crime


class Approval(BaseModel):
    """A person's approval of one high-impact call (extension): signed, bound to the call's parameters, used once."""

    approval_id: str
    proposal_hash: str
    incident_id: str
    approver: str
    issued_at: AwareDatetime
    expires_at: AwareDatetime
    provenance: Provenance


class ProposedAction(BaseModel):
    """What a rule or an agent wants done. Only the gate can turn it into a call."""

    department: str
    tier: Literal["reflex", "deliberate"]
    incident_id: str
    action: str
    actuator_id: str
    params: dict[str, Any]
    justification: str
    trust_ref: str | None
    evidence_reading_ids: list[str]
    direct_reading_id: str | None = None
    citations: list[str] = Field(default_factory=list)
    knowledge_citations: list[str] = Field(default_factory=list)  # playbook items and rules
    rule_id: str | None = None


class TimelineEvent(BaseModel):
    """CloudEvents 1.0 JSON envelope. `traceid` ties an event to the reading that caused it."""

    specversion: Literal["1.0"] = "1.0"
    id: str = Field(default_factory=lambda: clock.current().new_id("evt"))
    source: str = "city-brain"
    type: str
    time: AwareDatetime = Field(default_factory=utcnow)
    subject: str | None = None
    datacontenttype: Literal["application/json"] = "application/json"
    traceid: str | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    # Measured durations (extension). `data` is what a rerun must reproduce; `timing` is what it need not.
    timing: dict[str, float] | None = None
