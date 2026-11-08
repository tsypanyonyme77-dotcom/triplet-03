"""The funnel: how many things each stage of attention let through."""

from brain.contracts import TimelineEvent
from brain.mind.funnel import funnel


def test_the_funnel_counts_each_stage_from_the_timeline():
    kinds = ["brain.reading.received"] * 5 + ["brain.workspace.ignited"] * 2 + ["brain.workspace.deferred"] \
        + ["brain.deliberation.started"] + ["brain.action.result"] * 3 + ["brain.verdict.received"] * 5

    counts = funnel([TimelineEvent(type=kind) for kind in kinds])

    assert counts == {"readings": 5, "salient": 3, "ignited": 2, "model_calls": 1, "actions": 3}


