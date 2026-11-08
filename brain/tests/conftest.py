from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from brain.citygraph import MemoryGraphStore
from brain.contracts import (
    CONTRACT_VERSION,
    CitizenActivity,
    Incident,
    ReadingRef,
    SensorReading,
    TrustVerdict,
    VerdictStatus,
    utcnow,
)

ROOT = Path(__file__).resolve().parent.parent
T0 = datetime(2026, 11, 2, 14, 0, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _environment(monkeypatch):
    monkeypatch.setenv("BRAIN_HOME", str(ROOT))
    monkeypatch.setenv("TWIN_HMAC_SECRET", "test-twin-secret")
    monkeypatch.setenv("BRAIN_HMAC_SECRET", "test-brain-secret")


class World:
    """A small city graph that tests fill with readings and verdicts."""

    def __init__(self) -> None:
        self.store = MemoryGraphStore()
        self.store.load_topology(json.loads((ROOT / "scenarios/topology/small-city.json").read_text()))
        self._seq: dict[str, int] = {}
        self._verdicts = 0

    def reading(self, sensor_id: str, type: str, zone_id: str, value: dict, at_s: float,
                status: str = "trusted", expires_in_s: float = 120, confidence: float = 1.0) -> str:
        self._seq[sensor_id] = self._seq.get(sensor_id, 0) + 1
        self._verdicts += 1
        reading = SensorReading(
            contract_version=CONTRACT_VERSION, sensor_id=sensor_id, type=type, zone_id=zone_id,
            timestamp=T0 + timedelta(seconds=at_s), sequence_no=self._seq[sensor_id], value=value,
        )
        verdict = TrustVerdict(
            verdict_id=f"verdict-{self._verdicts:04d}",
            reading_ref=ReadingRef(sensor_id=sensor_id, sequence_no=reading.sequence_no),
            status=VerdictStatus(status), confidence=confidence, issued_at=utcnow(),
            expires_at=utcnow() + timedelta(seconds=expires_in_s),
        )
        self.store.add_reading(reading, verdict)
        if type == "citizen_activity":
            self.store.add_sighting(reading, CitizenActivity.model_validate(value))
        return reading.reading_id

    def crime(self, at_s: float = 10, status: str = "trusted", entity_id: str | None = None) -> Incident:
        value = {"anomaly_type": "robbery", "confidence": 0.9, **({"entity_id": entity_id} if entity_id else {})}
        reading_id = self.reading("cam-07-02", "cctv_anomaly", "zone-07", value, at_s, status)
        incident = Incident(incident_id="inc-0001", type="crime", zone_id="zone-07",
                            occurred_at=T0 + timedelta(seconds=at_s), evidence=[reading_id], departments=["POLICE"])
        self.store.add_incident(incident)
        self.store.link_evidence(reading_id, incident.incident_id)
        return incident

    def sighting(self, citizen_id: str, zone_id: str, at_s: float, speed: float = 4.0, activity: str = "walking",
                 heading: str | None = None, status: str = "trusted") -> str:
        value = {"citizen_id": citizen_id, "activity": activity, "speed_kmh": speed, "heading_zone_id": heading}
        return self.reading(f"cit-feed-{zone_id[-2:]}", "citizen_activity", zone_id, value, at_s, status)


@pytest.fixture
def world() -> World:
    return World()
