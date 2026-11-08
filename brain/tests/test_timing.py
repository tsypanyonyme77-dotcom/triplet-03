"""Measured time belongs in an event's `timing`, never in its data: data is what a rerun must reproduce, timing is what it need not."""

from brain.contracts import TimelineEvent
from brain.repro import run_events


async def test_measured_seconds_are_in_timing_and_not_in_data():
    events = await run_events("d3")

    prepared = next(e for e in events if e["type"] == "brain.options.prepared")

    assert "seconds" not in prepared["data"]["usage"]
    assert prepared["timing"]["seconds"] >= 0


def test_an_event_without_timing_does_not_carry_the_key():
    assert "timing" not in TimelineEvent(type="brain.started").model_dump(mode="json", exclude_none=True)
    assert TimelineEvent(type="brain.started", timing={"seconds": 0.5}).model_dump(mode="json")["timing"] == {"seconds": 0.5}
