"""Reproducibility: what a repeated run changes, found by comparing runs, never by assuming."""

from brain.repro import census, levels, normalise


def event(type: str, data: dict | None = None, *, id: str = "e1", time: str = "2026-11-04T10:00:00Z", **extra) -> dict:
    return {"specversion": "1.0", "id": id, "source": "city-brain", "type": type, "time": time, "subject": "inc-0001",
            "traceid": "cam-07-02:1", "data": data or {}, **extra}


def decision(zone: str) -> dict:
    return event("brain.decision.made", {"action": "dispatch_unit", "actuator_id": "police-dispatch-05", "params": {"zone_id": zone}})


def test_the_census_finds_a_field_that_differs_between_two_runs():
    first = [event("brain.options.prepared", {"usage": {"seconds": 0.0}}, id="a")]
    second = [event("brain.options.prepared", {"usage": {"seconds": 0.01}}, id="b", time="2026-11-04T10:05:00Z")]

    found = census([first, second])

    assert [(f.path, f.values) for f in found] == [("brain.options.prepared.data.usage.seconds", [0.0, 0.01])]


def test_normalise_removes_id_time_and_timing_and_nothing_else():
    raw = event("brain.reading.received", {"sensor_id": "cam-07-02"}, timing={"elapsed_ms": 3.2})

    assert normalise(raw) == {"specversion": "1.0", "source": "city-brain", "type": "brain.reading.received",
                              "subject": "inc-0001", "traceid": "cam-07-02:1", "data": {"sensor_id": "cam-07-02"}}


def test_decisions_identical_is_reported_separately_from_stream_identical():
    first = [decision("zone-07"), event("brain.options.prepared", {"usage": {"seconds": 0.0}}, id="a")]
    second = [decision("zone-07"), event("brain.options.prepared", {"usage": {"seconds": 0.01}}, id="b")]

    by_name = {level.name: level for level in levels([first, second])}

    assert by_name["decisions"].distinct == 1
    assert by_name["stream"].distinct == 2
    assert by_name["bytes"].distinct == 2


def test_repro_reports_the_first_differing_path():
    first = [event("brain.reading.received", {"zone_id": "zone-07"}), decision("zone-07")]
    second = [event("brain.reading.received", {"zone_id": "zone-07"}), decision("zone-09")]

    by_name = {level.name: level for level in levels([first, second])}

    assert by_name["decisions"].distinct == 2
    assert by_name["stream"].first_difference == "brain.decision.made.data.params.zone_id"


def test_runs_of_different_lengths_are_reported_as_a_length_difference():
    first = [decision("zone-07")]
    second = [decision("zone-07"), event("brain.incident.closed")]

    by_name = {level.name: level for level in levels([first, second])}

    assert by_name["stream"].distinct == 2
    assert by_name["stream"].first_difference == "event count: 1 against 2"


async def test_a_deterministic_run_gives_the_same_bytes_every_time():
    from brain.repro import collect

    runs = await collect("d2", 2, deterministic=True)

    by_name = {level.name: level for level in levels(runs)}
    assert by_name["bytes"].identical and by_name["stream"].identical
