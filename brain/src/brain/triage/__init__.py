"""Triage: decide which readings open an incident and which incidents a reading touches.

Deterministic on purpose. It owns the incident register for this process.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel

from brain.citygraph import MemoryGraphStore
from brain.config import Policy
from brain.contracts import (
    CctvAnomaly,
    CitizenActivity,
    EmergencyCall,
    Gunshot,
    Incident,
    SensorReading,
)
from brain.departments import Manifest, discover_manifests
from brain.departments.detectors import Detector, first_match, holds


class Triage:
    def __init__(self, policy: Policy, store: MemoryGraphStore, manifests: dict[str, Manifest] | None = None) -> None:
        self.policy = policy
        self.store = store
        # Non-crime incidents come from the packs' detectors, highest priority first (stable, so file order breaks ties).
        packs = manifests if manifests is not None else discover_manifests()[0]
        self._detectors: list[tuple[str, Detector]] = sorted(
            ((code, detector) for code, pack in packs.items() for detector in pack.detectors), key=lambda pair: -pair[1].priority
        )
        self.incidents: dict[str, Incident] = {}
        self._counter = 0
        self._stalled: set[str] = set()  # incidents already reported as stalled; new evidence clears the flag
        self._unrecognised: set[tuple[str, str]] = set()  # (kind, zone) of alarms already reported as unknown

    def snapshot(self) -> dict[str, Any]:
        return {"counter": self._counter, "stalled": sorted(self._stalled),
                "incidents": [incident.model_dump(mode="json") for incident in self.incidents.values()]}

    def restore(self, saved: dict[str, Any]) -> None:
        """Rebuild the register in place (other components hold a reference to it) and re-link the graph."""
        self._counter = int(saved.get("counter", 0))
        self._stalled = set(saved.get("stalled", []))
        self.incidents.clear()
        for dumped in saved.get("incidents", []):
            incident = Incident.model_validate(dumped)
            self.incidents[incident.incident_id] = incident
            MemoryGraphStore.add_incident(self.store, incident)
            for reading_id in incident.evidence:
                MemoryGraphStore.link_evidence(self.store, reading_id, incident.incident_id)

    def _is_crime_trigger(self, value: BaseModel | None) -> bool:
        triage = self.policy.triage
        if isinstance(value, CctvAnomaly):
            return value.anomaly_type in triage.crime_anomaly_types and value.confidence >= triage.min_confidence
        if isinstance(value, Gunshot):
            return value.detected and value.confidence >= triage.min_confidence
        if isinstance(value, EmergencyCall):
            return value.category == "police"
        return False

    def on_reading(self, reading: SensorReading, value: BaseModel | None) -> tuple[list[str], Incident | None]:
        """Returns (incident ids to evaluate, the incident this reading opened if any)."""
        if self._is_crime_trigger(value):
            return self._attach(reading, "crime", ["POLICE"], self.policy.triage.incident_merge_window_s)
        if (match := first_match(self._detectors, reading.type, self._data(reading, value))) is not None:
            code, detector = match
            return self._attach(reading, detector.incident, [code], self.policy.triage.condition_merge_window_s)
        if isinstance(value, CitizenActivity):
            return self._incidents_near(reading, value.zone_id or reading.zone_id), None
        return [], None

    @staticmethod
    def _data(reading: SensorReading, value: BaseModel | None) -> dict[str, Any]:
        """What detectors see: the typed value (defaults filled, unknown fields gone), or the raw value of an unknown type."""
        return value.model_dump() if value is not None else dict(reading.value)

    def cleared_by(self, reading: SensorReading, value: BaseModel | None) -> list[str]:
        """Open incidents this reading says are over. Nothing changes: the caller checks the verdict, then closes."""
        data = self._data(reading, value)
        ended = {d.incident for _, d in self._detectors if d.reading == reading.type and d.clear and holds(d.clear, data)}
        return [i.incident_id for i in self.incidents.values()
                if i.status == "open" and i.type in ended and i.zone_id == reading.zone_id]

    def _attach(self, reading: SensorReading, type: str, departments: list[str], window_s: float) -> tuple[list[str], Incident | None]:
        """Add the reading to the open incident of this type and place, or open one."""
        merge = timedelta(seconds=window_s)
        for incident in self.incidents.values():
            same_place = incident.zone_id == reading.zone_id
            if incident.status == "open" and incident.type == type and same_place:
                if abs(reading.timestamp - incident.occurred_at) <= merge:
                    incident.evidence.append(reading.reading_id)
                    self._stalled.discard(incident.incident_id)
                    self.store.link_evidence(reading.reading_id, incident.incident_id)
                    return [incident.incident_id], None

        self._counter += 1
        incident = Incident(
            incident_id=f"inc-{self._counter:04d}",
            type=type,
            zone_id=reading.zone_id,
            occurred_at=reading.timestamp,
            evidence=[reading.reading_id],
            departments=list(departments),
        )
        self.incidents[incident.incident_id] = incident
        self.store.add_incident(incident)
        self.store.link_evidence(reading.reading_id, incident.incident_id)
        return [incident.incident_id], incident

    def _incidents_near(self, reading: SensorReading, zone_id: str) -> list[str]:
        scoring = self.policy.scoring
        touched = []
        for incident in self.incidents.values():
            if incident.status != "open" or incident.type != "crime":
                continue
            start = incident.occurred_at - timedelta(seconds=scoring.copresence_window_s.before)
            end = incident.occurred_at + timedelta(seconds=scoring.flight_window_s)
            near = zone_id in self.store.zones_within(incident.zone_id, scoring.flight_radius_hops)
            if near and start <= reading.timestamp <= end:
                touched.append(incident.incident_id)
        return touched

    def unrecognised(self, reading: SensorReading, value: BaseModel | None) -> str | None:
        """An alarm the Twin sent that no pack's detector and no crime rule recognises, named once per kind and zone; None for anything else.

        A camera anomaly above the confidence line that is not a crime type or a collision, or an emergency call whose category is `other`: the
        Brain cannot open an incident for it, so a person should hear of it instead of nothing happening."""
        triage = self.policy.triage
        if self._is_crime_trigger(value) or first_match(self._detectors, reading.type, self._data(reading, value)) is not None:
            return None
        if isinstance(value, CctvAnomaly) and value.confidence >= triage.min_confidence:
            kind = f"cctv_anomaly:{value.anomaly_type}"
        elif isinstance(value, EmergencyCall) and value.category == "other":
            kind = "emergency_call:other"
        else:
            return None
        if (kind, reading.zone_id) in self._unrecognised:
            return None
        self._unrecognised.add((kind, reading.zone_id))
        return kind

    def stalled(self, now: datetime) -> list[Incident]:
        """Open incidents with no new evidence for `stall_s` before `now`, each reported once until new evidence joins.

        shortcut: checked when a reading arrives, so a city that goes completely silent is not noticed; add a timer if the Twin streams slowly.
        """
        limit = self.policy.triage.stall_s
        if limit <= 0:
            return []
        found = []
        for incident in self.incidents.values():
            if incident.status != "open" or incident.incident_id in self._stalled:
                continue
            seen = [r.timestamp for rid in incident.evidence if (r := self.store.reading(rid)) is not None]
            if (now - max(seen, default=incident.occurred_at)).total_seconds() >= limit:
                self._stalled.add(incident.incident_id)
                found.append(incident)
        return found

    def close(self, incident_id: str, outcome: str) -> Incident | None:
        incident = self.incidents.get(incident_id)
        if incident is None or incident.status == "closed":
            return None
        incident.status = "closed"
        incident.outcome = outcome
        return incident
