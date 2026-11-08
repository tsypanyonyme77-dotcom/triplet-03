"""An event is a fact at the moment it was emitted: nothing that happens later may change it."""

from brain.timeline import MemorySink, Timeline


def test_an_event_keeps_the_data_it_was_emitted_with():
    sink = MemorySink()
    timeline = Timeline([sink])
    evidence = ["wl-01-01#5"]

    timeline.emit("brain.incident.opened", "inc-0001", {"evidence": evidence, "zone": {"id": "zone-01"}})
    evidence.append("wl-01-01#6")

    assert sink.events[0].data["evidence"] == ["wl-01-01#5"]
