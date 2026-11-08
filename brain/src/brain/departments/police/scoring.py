"""Suspect scoring: how strongly does the evidence tie one entity to one crime incident?

Deterministic and explainable. Features are behavioural only. Each feature's weight is
scaled by the Guardian's trust in the readings behind it, so a spoofed reading cannot
carry anyone over the threshold:

    score = sigmoid(bias + sum(weight_i * x_i * trust_i))

Running from a crime scene is evidence only when it singles someone out. People flee out
of fear, so the flight feature is divided among everyone at the scene who left fast, and
nobody is named on flight alone until the others who were there have been seen again
(or `settle_s` has passed). A camera identification needs neither.
"""

from __future__ import annotations

import math
from datetime import timedelta

from brain.citygraph import MemoryGraphStore, Sighting
from brain.config import ScoringPolicy
from brain.contracts import Assessment, CctvAnomaly, FeatureHit, Incident, VerdictStatus


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def _trust(store: MemoryGraphStore, policy: ScoringPolicy, reading_id: str) -> float:
    verdict = store.verdict_of(reading_id)
    return policy.trust_weights.get(verdict.status.value, 0.0) if verdict else 0.0


def _moving_away(sighting: Sighting, scene: str) -> bool:
    if sighting.zone_id != scene:
        return True
    return sighting.heading_zone_id is not None and sighting.heading_zone_id != scene


def _within(store: MemoryGraphStore, zone_id: str, scene: str, hops: int) -> bool:
    distance = store.hop_distance(zone_id, scene)
    return distance is not None and distance <= hops


def _fleeing(sightings: list[Sighting], incident: Incident, store: MemoryGraphStore, policy: ScoringPolicy) -> list[Sighting]:
    """The sightings that count as leaving the scene fast after the crime."""
    scene, crime_time = incident.zone_id, incident.occurred_at
    return [
        s for s in sightings
        if crime_time < s.time <= crime_time + timedelta(seconds=policy.flight_window_s)
        and (s.speed_kmh >= policy.flight_speed_kmh or s.activity in policy.flight_activities)
        and _within(store, s.zone_id, scene, policy.flight_radius_hops)
        and _moving_away(s, scene)
    ]


def _others_at_scene(
    incident: Incident, entity_id: str, store: MemoryGraphStore, policy: ScoringPolicy
) -> tuple[list[str], list[str], list[str]]:
    """What the other people at the scene did afterwards.

    Returns (who also left fast on a trusted reading, who left fast on any reading, who has
    not been seen since the crime). An untrusted sighting can no more excuse a suspect than
    accuse one, so only the first list dilutes the trust-weighted score.
    """
    crime_time, window = incident.occurred_at, policy.copresence_window_s
    present = store.entities_seen(
        {incident.zone_id}, crime_time - timedelta(seconds=window.before), crime_time + timedelta(seconds=window.after)
    )
    settled = store.latest_at is not None and store.latest_at - crime_time >= timedelta(seconds=policy.settle_s)
    fled_trusted, fled_any, unaccounted = [], [], []
    for other in present:
        if other == entity_id:
            continue
        sightings = store.sightings(other)
        fleeing = _fleeing(sightings, incident, store, policy)
        if fleeing:
            fled_any.append(other)
            if any(_trust(store, policy, s.reading_id) >= 1.0 for s in fleeing):
                fled_trusted.append(other)
        elif not settled and not any(s.time > crime_time for s in sightings):
            unaccounted.append(other)
    return fled_trusted, fled_any, unaccounted


def assess(incident: Incident, entity_id: str, store: MemoryGraphStore, policy: ScoringPolicy) -> Assessment:
    scene, crime_time = incident.zone_id, incident.occurred_at
    sightings = store.sightings(entity_id)
    # Everything a suspect claim rests on depends on the crime having happened.
    credibility = max((_trust(store, policy, r) for r in incident.evidence), default=0.0)
    features: list[FeatureHit] = []

    window = policy.copresence_window_s
    at_scene = [
        s for s in sightings
        if s.zone_id == scene
        and crime_time - timedelta(seconds=window.before) <= s.time <= crime_time + timedelta(seconds=window.after)
    ]
    if at_scene:
        # The best-vouched sighting, then the one nearest the crime in time.
        closest = min(at_scene, key=lambda s: (-_trust(store, policy, s.reading_id), abs(s.time - crime_time)))
        features.append(FeatureHit(
            name="copresence", x=1.0, weight=policy.weights["copresence"],
            trust=min(credibility, _trust(store, policy, closest.reading_id)),
            reading_ids=[closest.reading_id], note=f"seen in {scene} at the time of the crime",
        ))
        store.mark_at_scene(entity_id, incident.incident_id)

    fled_with, fled_any, unaccounted = _others_at_scene(incident, entity_id, store, policy)
    fleeing = _fleeing(sightings, incident, store, policy)
    if fleeing:
        # The best-vouched sighting of the flight, so a trusted sensor can confirm a doubtful one.
        best = max(fleeing, key=lambda s: _trust(store, policy, s.reading_id))
        shared = f"; one of {len(fled_with) + 1} people who left the scene fast" if fled_with else ""
        features.append(FeatureHit(
            name="flight", x=round(1.0 / (1 + len(fled_with)), 4), weight=policy.weights["flight"],
            trust=min(credibility, _trust(store, policy, best.reading_id)),
            reading_ids=[best.reading_id],
            note=f"moving away from {scene} at {best.speed_kmh:.1f} km/h after the crime{shared}",
        ))

    other_scenes = store.scenes_attended(entity_id) - {incident.incident_id}
    if other_scenes:
        features.append(FeatureHit(
            name="repeat", x=min(len(other_scenes), 2) / 2, weight=policy.weights["repeat"],
            trust=credibility, note=f"also present at {len(other_scenes)} other crime scene{'' if len(other_scenes) == 1 else 's'}",
        ))

    direct_reading_id = None
    for reading_id in incident.evidence:
        reading = store.reading(reading_id)
        if reading and reading.type == "cctv_anomaly":
            if CctvAnomaly.model_validate(reading.value).entity_id == entity_id:
                direct_reading_id = reading_id
                features.append(FeatureHit(
                    name="direct", x=1.0, weight=policy.weights["direct"],
                    trust=_trust(store, policy, reading_id), reading_ids=[reading_id],
                    note="identified by a camera at the scene",
                ))
                break

    score = _sigmoid(policy.bias + sum(f.weight * f.x * f.trust for f in features))
    # What the data says if every reading were believed, including every report of someone else fleeing.
    raw_score = _sigmoid(policy.bias + sum(
        f.weight * (1.0 / (1 + len(fled_any)) if f.name == "flight" else f.x) for f in features
    ))

    evidence = list(dict.fromkeys(incident.evidence + [r for f in features for r in f.reading_ids]))
    trusted_sources, discounted = set(), []
    for reading_id in evidence:
        verdict = store.verdict_of(reading_id)
        if verdict and verdict.status == VerdictStatus.TRUSTED:
            trusted_sources.add(reading_id.split("#")[0])
        else:
            discounted.append({
                "reading_id": reading_id,
                "status": verdict.status.value if verdict else "missing",
                "verdict_id": verdict.verdict_id if verdict else "",
            })

    direct_trusted = direct_reading_id is not None and _trust(store, policy, direct_reading_id) >= 1.0
    corroborated = len(trusted_sources) >= 2 and not unaccounted
    if score >= policy.suspect_threshold and (corroborated or direct_trusted):
        level = "suspect"
    elif score >= policy.poi_threshold:
        level = "poi"
    else:
        level = "none"

    return Assessment(
        incident_id=incident.incident_id,
        entity_id=entity_id,
        score=round(score, 4),
        raw_score=round(raw_score, 4),
        level=level,
        features=features,
        evidence_reading_ids=evidence,
        trusted_sources=sorted(trusted_sources),
        direct_reading_id=direct_reading_id,
        last_zone_id=sightings[-1].zone_id if sightings else None,
        heading_zone_id=sightings[-1].heading_zone_id if sightings else None,
        discounted=discounted,
        fled_with=fled_with,
        unaccounted=unaccounted,
    )
