"""The funnel: what each stage of attention let through, counted from the timeline.

Readings in, incidents the workspace found worth a slot (salient), those that got one (ignited), model
calls made, actions taken. A burst of events shows as a wide top and a narrow bottom.
"""

from __future__ import annotations

from collections.abc import Iterable

from brain.contracts import TimelineEvent


def funnel(events: Iterable[TimelineEvent]) -> dict[str, int]:
    kinds = [event.type for event in events]
    ignited = kinds.count("brain.workspace.ignited")
    return {
        "readings": kinds.count("brain.reading.received"),
        "salient": ignited + kinds.count("brain.workspace.deferred"),
        "ignited": ignited,
        "model_calls": kinds.count("brain.deliberation.started"),
        "actions": kinds.count("brain.action.result"),
    }
