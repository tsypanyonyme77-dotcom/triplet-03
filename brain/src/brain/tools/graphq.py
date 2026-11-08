"""Read-only queries over the live city graph, for agents building a case."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from brain.citygraph import MemoryGraphStore
from brain.config import ScoringPolicy
from brain.contracts import Incident


def _verdict(store: MemoryGraphStore, reading_id: str) -> str:
    verdict = store.verdict_of(reading_id)
    return verdict.status.value if verdict else "missing"


def entity_timeline(store: MemoryGraphStore, entity_id: str, limit: int = 12) -> list[dict[str, Any]]:
    """The most recent sightings of one entity, oldest first, each with its Guardian verdict."""
    return [
        {
            "reading_id": s.reading_id, "time": s.time.isoformat(), "zone_id": s.zone_id,
            "activity": s.activity, "speed_kmh": s.speed_kmh, "heading_zone_id": s.heading_zone_id,
            "verdict": _verdict(store, s.reading_id),
        }
        for s in store.sightings(entity_id)[-limit:]
    ]


def copresence(store: MemoryGraphStore, incident: Incident, policy: ScoringPolicy, subject_id: str) -> dict[str, Any]:
    """The other people seen at the scene around the time of the incident, and whether each moved fast afterwards.

    Lets an analyst tell one person fleeing from a crowd scattering. The subject is reported
    separately so that their own flight is never counted as someone else's.
    """
    window = policy.copresence_window_s
    start = incident.occurred_at - timedelta(seconds=window.before)
    end = incident.occurred_at + timedelta(seconds=window.after)
    flight_end = incident.occurred_at + timedelta(seconds=policy.flight_window_s)

    def describe(entity_id: str) -> dict[str, Any]:
        after = [s for s in store.sightings(entity_id) if incident.occurred_at < s.time <= flight_end]
        fast = [s for s in after if s.speed_kmh >= policy.flight_speed_kmh or s.activity in policy.flight_activities]
        return {
            "entity_id": entity_id,
            "sightings_after": len(after),
            "moved_fast_after": bool(fast),
            "max_speed_kmh_after": max((s.speed_kmh for s in after), default=0.0),
            "last_zone_id": store.sightings(entity_id)[-1].zone_id,
        }

    present = store.entities_seen({incident.zone_id}, start, end)
    others = [describe(entity_id) for entity_id in present if entity_id != subject_id]
    subject = describe(subject_id) if subject_id in present else None
    fled = sum(1 for person in others if person["moved_fast_after"])
    # Stated in words by code, because models have read a bare zero here the wrong way round.
    if subject is None:
        conclusion = "The subject was not seen at the scene around the time of the incident."
    elif not subject["moved_fast_after"]:
        conclusion = "The subject did not leave the scene fast."
    elif fled == 0:
        conclusion = "Only the subject left the scene fast. Their flight singles them out and counts as evidence against them."
    else:
        conclusion = (f"{fled} other {'person' if fled == 1 else 'people'} at the scene also left fast. "
                      "Flight does not single the subject out and is weak evidence.")
    return {"subject": subject, "others_at_scene": others, "others_who_moved_fast_after": fled, "conclusion": conclusion}


def incident_evidence(store: MemoryGraphStore, incident: Incident) -> list[dict[str, Any]]:
    """The readings that opened the incident, with their verdicts."""
    evidence = []
    for reading_id in incident.evidence:
        reading = store.reading(reading_id)
        if reading is None:
            continue
        evidence.append({
            "reading_id": reading_id, "type": reading.type, "zone_id": reading.zone_id,
            "time": reading.timestamp.isoformat(), "verdict": _verdict(store, reading_id),
        })
    return evidence
