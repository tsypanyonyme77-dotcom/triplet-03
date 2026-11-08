"""The attention report: where the workspace's slots and the team's runs went, counted from the timeline.

Waits are counted in readings (how many readings the Brain read between two events), not seconds, so a number is the
same on every machine and at every playback speed. Nothing here is computed by a model.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from brain.contracts import TimelineEvent


def attention_report(events: Iterable[TimelineEvent], team_types: tuple[str, ...] = ("crime",)) -> dict[str, Any]:
    """Per incident and in total: lit or not, waited how long, and what the slots and the team's runs were spent on.

    `team_types` are the incident types an agent team can act on; a slot spent on any other type is `slots_on_teamless`.
    """
    incidents: dict[str, dict[str, Any]] = {}
    scores: dict[str, float] = {}
    readings = lit = deferred_events = team_runs = teamless = inversions = 0
    for event in events:
        kind, subject, data = event.type, event.subject, event.data
        if kind == "brain.reading.received":
            readings += 1
        elif kind == "brain.incident.opened":
            incidents[subject] = {"type": data.get("type"), "opened_at": readings, "lit_at": None, "first_deferred_at": None,
                                  "deferred_times": 0, "waited_readings": None}
        elif kind == "brain.workspace.ignited" and subject in incidents:
            row = incidents[subject]
            lit += 1
            row["lit_at"] = readings
            row["waited_readings"] = readings - row["opened_at"]
            scores[subject] = data.get("salience", 0.0)
            if data.get("slot", True) and data.get("type") not in team_types:
                teamless += 1
        elif kind == "brain.workspace.deferred" and subject in incidents:
            row = incidents[subject]
            deferred_events += 1
            row["deferred_times"] += 1
            if row["first_deferred_at"] is None:
                row["first_deferred_at"] = readings
            weakest = min((scores.get(held, 1.0) for held in data.get("holding", [])), default=1.0)
            if data.get("salience", 0.0) > weakest:
                inversions += 1
        elif kind == "brain.workspace.released":
            scores.pop(subject, None)
        elif kind == "brain.deliberation.started":
            team_runs += 1
    waits = [row["waited_readings"] for row in incidents.values() if row["waited_readings"] is not None]
    waits += [readings - row["first_deferred_at"] for row in incidents.values() if row["lit_at"] is None and row["first_deferred_at"] is not None]
    return {
        "incidents": incidents,
        "lit": lit,
        "deferred_events": deferred_events,
        "denied": sum(1 for row in incidents.values() if row["lit_at"] is None and row["deferred_times"]),
        "below_the_bar": sum(1 for row in incidents.values() if row["lit_at"] is None and not row["deferred_times"]),
        "team_runs": team_runs,
        "slots_on_teamless": teamless,
        "longest_wait_readings": max(waits, default=0),
        "inversions": inversions,
    }
