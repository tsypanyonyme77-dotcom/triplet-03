"""Salience: how much an incident deserves the Brain's scarce attention.

A weighted mean of five numbers the Brain can observe (no model is involved), multiplied by the share
of the evidence that the Guardian trusts (a trusted verdict counts in full from `trust_full_at` upward in
confidence and in proportion below it), so an incident built on untrusted readings scores zero and
cannot take a model call away from a real one, and by freshness, so attention fades when nothing new
arrives. Surprise (how far the newest evidence sits from what the forward models predicted) adds a
boost on top, never enough to lift untrusted evidence. The reflex tier keeps acting whatever the score is.
"""

from __future__ import annotations

from datetime import datetime

from brain.citygraph import MemoryGraphStore
from brain.config import WorkspacePolicy
from brain.contracts import Incident, VerdictStatus


def salience(
    incident: Incident, store: MemoryGraphStore, others: list[Incident], now: datetime, policy: WorkspacePolicy,
    surprise: float = 0.0, urgency: float = 0.0,
) -> tuple[float, dict[str, float]]:
    """Returns (score, the eight features), all between 0 and 1. `others` are the other known incidents;
    `surprise` and `urgency` are 0 to 1, from the forward models and the level forecast."""
    trusted, sources, newest = 0.0, set(), None
    for reading_id in incident.evidence:
        verdict = store.verdict_of(reading_id)
        if verdict is not None and verdict.status == VerdictStatus.TRUSTED:
            trusted += min(verdict.confidence / policy.trust_full_at, 1.0)
            reading = store.reading(reading_id)
            # `cause`: two sensors of one kind in one zone are one witness, not two.
            sources.add((reading.type, reading.zone_id) if policy.corroboration_by == "cause" and reading is not None else reading_id.split("#")[0])
        reading = store.reading(reading_id)
        if reading is not None and (newest is None or reading.timestamp > newest):
            newest = reading.timestamp

    others = [other for other in others if other.incident_id != incident.incident_id]
    nearby = store.zones_within(incident.zone_id, policy.cluster_radius_hops)
    age_s = max((now - newest).total_seconds(), 0.0) if newest is not None else 0.0
    features = {
        "severity": policy.severity.get(incident.type, 0.5),
        "trust": trusted / len(incident.evidence) if incident.evidence else 0.0,
        "corroboration": min(len(sources) / 3, 1.0),
        "novelty": 1 / (1 + sum(1 for o in others if o.type == incident.type and o.zone_id == incident.zone_id)),
        "clustering": min(sum(1 for o in others if o.status == "open" and o.zone_id in nearby) / 2, 1.0),
        "freshness": 0.5 ** (age_s / policy.freshness_halflife_s),
        "surprise": min(max(surprise, 0.0), 1.0),
        "urgency": min(max(urgency, 0.0), 1.0),
    }
    weighted = {name: policy.weights[name] for name in policy.weights if name in features}
    total = sum(weighted.values())
    mean = sum(weight * features[name] for name, weight in weighted.items()) / total if total else 0.0
    damp = features["trust"] * features["freshness"]
    score = min(mean * damp + (policy.surprise_boost * features["surprise"] + policy.urgency_boost * features["urgency"]) * damp, 1.0)
    return round(score, 3), {name: round(value, 3) for name, value in features.items()}
