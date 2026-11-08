"""Scenario baseline streams: a calm day described as a few lines instead of hundreds of events."""

import copy

from brain.scenario import expand_streams

STREAM = {
    "sensor_id": "wl-01-01", "type": "water_level", "zone_id": "zone-01",
    "from_ms": 0, "to_ms": 3000, "every_ms": 1000,
    "base": {"level_m": 0.3, "flag": True, "label": "calm"}, "noise": {"level_m": 0.02}, "seed": 4,
}


def scenario(**stream_changes):
    return {"id": "x", "events": [], "streams": [{**STREAM, **stream_changes}]}


def test_a_stream_expands_to_one_event_per_interval():
    events = expand_streams(scenario())["events"]

    assert [e["at_ms"] for e in events] == [0, 1000, 2000]
    for event in events:
        assert event["sensor_id"] == "wl-01-01" and event["type"] == "water_level" and event["zone_id"] == "zone-01"
        assert event["value"]["flag"] is True and event["value"]["label"] == "calm"
        assert event["value"]["level_m"] != 0.3


def test_the_same_seed_gives_the_same_noise_and_a_different_seed_does_not():
    levels = lambda s: [e["value"]["level_m"] for e in expand_streams(s)["events"]]  # noqa: E731

    assert levels(scenario()) == levels(scenario())
    assert levels(scenario()) != levels(scenario(seed=5))


def test_noise_respects_clamps_and_keeps_integers_integers():
    wild = scenario(
        type="traffic_camera", base={"vehicle_count": 14, "congestion_score": 0.2},
        noise={"vehicle_count": 9, "congestion_score": 2.0}, clamp={"congestion_score": [0, 1]},
        from_ms=0, to_ms=200_000, every_ms=1000,
    )

    values = [e["value"] for e in expand_streams(wild)["events"]]

    assert len(values) == 200
    assert all(type(v["vehicle_count"]) is int for v in values)
    assert all(0 <= v["congestion_score"] <= 1 for v in values)


def test_generated_and_hand_written_events_merge_in_time_order():
    mixed = scenario()
    mixed["events"] = [{"at_ms": 1000, "sensor_id": "hand", "type": "water_level", "zone_id": "zone-01", "value": {}},
                       {"at_ms": 500, "sensor_id": "hand", "type": "water_level", "zone_id": "zone-01", "value": {}}]

    events = expand_streams(mixed)["events"]

    assert [e["at_ms"] for e in events] == [0, 500, 1000, 1000, 2000]
    assert [e["sensor_id"] for e in events if e["at_ms"] == 1000] == ["wl-01-01", "hand"]
    assert "streams" not in expand_streams(mixed)


def test_a_scenario_without_streams_is_returned_unchanged():
    plain = {"id": "x", "events": [{"at_ms": 5}]}
    before = copy.deepcopy(plain)

    assert expand_streams(plain) == before
    assert plain == before
