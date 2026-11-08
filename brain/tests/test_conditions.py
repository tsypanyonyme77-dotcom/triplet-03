"""Floods, jams, fires and accidents: the condition reflex path from reading to gated actuator call."""

import json

from brain import config
from brain.scenario import expand_streams, inproc_partners, load_scenario
from tests.test_scenarios import failed, play


def scenario(events, guardian=None, **extra):
    topology = json.loads((config.home() / "scenarios/topology/small-city.json").read_text())
    return {"id": "t", "topology": topology, "guardian": guardian or {"default": "trusted"}, "events": events, "expect": {}, **extra}


def water(at_ms, level, sensor="wl-01-01"):
    return {"at_ms": at_ms, "sensor_id": sensor, "type": "water_level", "zone_id": "zone-01", "value": {"level_m": level}}


def camera(at_ms, congestion, smoke=False, sensor="tcam-05-01", zone="zone-05"):
    return {"at_ms": at_ms, "sensor_id": sensor, "type": "traffic_camera", "zone_id": zone,
            "value": {"congestion_score": congestion, "vehicle_count": 30, "avg_speed_kmh": 8.0, "smoke_detected": smoke}}


def call(at_ms, category, sensor, zone):
    return {"at_ms": at_ms, "sensor_id": sensor, "type": "emergency_call", "zone_id": zone,
            "value": {"call_id": f"call-{at_ms}", "category": category, "caller_confidence": 0.6}}


def blocked(result):
    return sorted(e.data["check"] for e in result.sink.of("brain.action.blocked"))


async def test_a_flood_reading_reaches_an_alert_and_a_refused_valve_call():
    events = [water(100, 1.2), water(200, 1.4), call(300, "flood", "call-feed-01", "zone-01")]

    result = await play(scenario(events))

    alerts = [c for c in result.actuator_calls if c["call"]["action"] == "broadcast_alert"]
    assert [a["call"]["params"]["zone_id"] for a in alerts] == ["zone-01"]
    assert [c["call"]["action"] for c in result.actuator_calls] == ["broadcast_alert"]
    # One source cannot back a high-impact call; two can, and then it waits for a human.
    assert blocked(result) == ["evidence", "human_approval"]


async def test_a_storm_of_jam_readings_gives_one_incident_and_one_signal_call():
    storm = {"streams": [{"sensor_id": "tcam-05-01", "type": "traffic_camera", "zone_id": "zone-05", "from_ms": 0,
                          "to_ms": 20_000, "every_ms": 100,
                          "base": {"congestion_score": 0.85, "vehicle_count": 40, "avg_speed_kmh": 5.0}}]}

    result = await play(expand_streams(scenario([], **storm)))

    assert len(result.sink.of("brain.reading.received")) == 200
    assert len(result.sink.of("brain.incident.opened")) == 1
    signals = [c for c in result.actuator_calls if c["call"]["action"] == "set_signal_phase"]
    assert len(signals) == 1
    assert signals[0]["call"]["params"] == {"intersection_id": "sig-05-01", "phase": "green", "duration_s": 120}
    assert signals[0]["call"]["actuator_id"] == "signal-05-01"


async def test_an_untrusted_flood_reading_opens_an_incident_but_moves_nothing():
    result = await play(scenario([water(100, 1.3)], guardian={"default": "trusted", "overrides": {"wl-01-01": "untrusted"}}))

    assert len(result.sink.of("brain.incident.opened")) == 1
    assert result.actuator_calls == []
    assert blocked(result) and set(blocked(result)) == {"trust_ref"}


async def test_an_untrusted_recovery_reading_does_not_close_the_incident():
    guardian = {"default": "trusted", "overrides": {"wl-01-02": "untrusted"}}
    result = await play(scenario([water(100, 1.3), water(200, 0.4, sensor="wl-01-02")], guardian=guardian))
    assert result.sink.of("brain.incident.closed") == []

    result = await play(scenario([water(100, 1.3), water(200, 0.4, sensor="wl-01-02"), water(300, 0.4)], guardian=guardian))
    closed = result.sink.of("brain.incident.closed")
    assert len(closed) == 1 and closed[0].data["outcome"] == "cleared"


async def test_a_twin_without_signal_control_gets_a_blocked_jam_response():
    result = await play(scenario([camera(100, 0.85)]), inproc_partners(frozenset({"set_signal_phase"})))

    assert result.actuator_calls == []
    assert blocked(result) == ["capability"]


async def test_a_fire_needs_two_independent_sources_before_a_unit_is_sent():
    smoke_only = await play(scenario([camera(100, 0.2, smoke=True, sensor="tcam-06-01", zone="zone-06")]))
    assert smoke_only.actuator_calls == [] and blocked(smoke_only) == ["evidence"]

    both = await play(scenario([camera(100, 0.2, smoke=True, sensor="tcam-06-01", zone="zone-06"),
                                call(500, "fire", "call-feed-06", "zone-06")]))
    dispatches = [c["call"] for c in both.actuator_calls if c["call"]["action"] == "dispatch_unit"]
    assert [d["params"]["unit_type"] for d in dispatches] == ["fire"]
    assert dispatches[0]["actuator_id"] == "fire-dispatch-04"


async def test_crime_scenarios_do_not_touch_the_condition_path():
    result = await play(load_scenario("t14"))

    assert result.passed, failed(result)
    rules = " ".join(e.data["justification"] for e in result.sink.of("brain.decision.made"))
    assert "POL-" in rules and not any(prefix in rules for prefix in ("FIR-", "MOB-", "UTL-"))
    assert {e.data["department"] for e in result.sink.of("brain.decision.made")} == {"POLICE"}


def calm_levels(until_ms=4000, every_ms=500, sensor="wl-01-01"):
    return [{"sensor_id": sensor, "type": "water_level", "zone_id": "zone-01", "from_ms": 0, "to_ms": until_ms,
             "every_ms": every_ms, "base": {"level_m": 0.30}, "noise": {"level_m": 0.01}, "clamp": {"level_m": [0.25, 0.35]}, "seed": 3}]


def surprises(result):
    return result.sink.of("brain.percept.surprise")


async def test_a_lone_spike_opens_an_incident_but_sends_nothing_until_another_source_agrees():
    result = await play(expand_streams(scenario([water(6000, 2.4)], streams=calm_levels())))

    assert len(result.sink.of("brain.incident.opened")) == 1
    assert result.actuator_calls == []
    held = result.sink.of("brain.action.blocked")
    assert [e.data["check"] for e in held] == ["surprise"]
    assert "jumped far outside" in held[0].data["reason"] and "wl-01-01" in held[0].data["reason"]
    assert surprises(result)[0].data["doubted"] is True


async def test_a_real_flood_is_confirmed_by_its_second_reading():
    events = [water(5000, 1.1), water(5500, 1.3)]

    result = await play(expand_streams(scenario(events, streams=calm_levels())))

    alerts = [c for c in result.actuator_calls if c["call"]["action"] == "broadcast_alert"]
    assert len(alerts) == 1
    assert [e.data["run"] for e in surprises(result)] == [1, 2]
    order = result.sink.types()
    assert order.index("brain.action.blocked") < order.index("brain.decision.made")  # held on the first, sent on the second


async def test_a_second_source_clears_the_doubt():
    events = [water(6000, 2.4), call(6500, "flood", "call-feed-01", "zone-01")]

    result = await play(expand_streams(scenario(events, streams=calm_levels())))

    alerts = [c for c in result.actuator_calls if c["call"]["action"] == "broadcast_alert"]
    assert len(alerts) == 1
    assert [e.data["check"] for e in result.sink.of("brain.action.blocked")][0] == "surprise"


async def test_the_held_action_names_the_surprise_check_once():
    events = [water(6000, 2.4), water(6200, 0.30)]

    result = await play(expand_streams(scenario(events, streams=calm_levels())))

    assert [e.data["check"] for e in result.sink.of("brain.action.blocked")] == ["surprise"]


# --- units sent for a fire or an accident come home when they report it ---------------------------------------------------


def fire_events():
    return [call(100, "fire", "call-feed-06", "zone-06"), camera(200, 0.2, smoke=True, sensor="tcam-06-01", zone="zone-06")]


async def test_a_fire_unit_that_reports_it_is_returning_is_released_and_the_fire_incident_closes():
    result = await play(scenario(fire_events()))

    released = result.sink.of("brain.units.released")
    closed = result.sink.of("brain.incident.closed")
    assert released and released[0].data["units"][0]["recalled"] is False and "returning" in released[0].data["cause"]
    assert [c.data["outcome"] for c in closed] == ["returned"]


async def test_a_police_unit_that_is_recalled_and_reports_returning_changes_nothing_more():
    result = await play(load_scenario("t14"))

    assert [e.data["outcome"] for e in result.sink.of("brain.incident.closed")] == ["apprehended"]
