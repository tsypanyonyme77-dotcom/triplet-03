"""The Brain's own actions have expected effects on what it senses: a fall it caused is not a surprise."""

from datetime import timedelta

from brain.config import Effect, ForwardPolicy
from brain.contracts import TimelineEvent
from brain.mind.effects import ActionEffects
from brain.mind.forward import ForwardModels
from tests.conftest import T0
from tests.test_forward import Feed

EFFECTS = {"set_valve_state": Effect(sensor_type="water_level", changes={"level_m": -1}, delay_s=0, window_s=60)}


def flooded_feed(**policy):
    feed = Feed(ForwardModels(ForwardPolicy(**policy)))
    feed.calm(30, level=1.20)
    return feed


def expect(feed, start_s=31, end_s=91, direction=-1, zone="zone-01", sensor_type="water_level", field="level_m"):
    feed.models.expect(zone, sensor_type, field, direction, T0 + timedelta(seconds=start_s), T0 + timedelta(seconds=end_s), "set_valve_state")


def test_without_an_expectation_a_fall_is_a_doubted_surprise():
    feed = flooded_feed()

    _, found = feed.send(0.30)

    assert found and found[0].doubted and found[0].explained is None


def test_an_expected_fall_after_an_own_action_is_explained_and_not_doubted():
    feed = flooded_feed()
    expect(feed)

    reading, found = feed.send(0.30)

    (surprise,) = found
    assert surprise.explained == "set_valve_state" and not surprise.doubted and not surprise.rebaselined
    assert not feed.models.is_doubted(reading.reading_id)


def test_the_baseline_follows_an_explained_change_so_the_next_reading_is_ordinary():
    feed = flooded_feed()
    expect(feed)

    feed.send(0.80)  # still falling
    feed.send(0.30)

    assert feed.send(0.31)[1] == []
    assert abs(feed.models.baseline("wl-01-01", "level_m")[0] - 0.30) < 0.03


def test_a_change_before_the_delay_or_after_the_window_is_not_explained():
    early = flooded_feed()
    expect(early, start_s=50, end_s=90)
    late = flooded_feed()
    expect(late, start_s=0, end_s=20)

    assert early.send(0.30)[1][0].explained is None
    assert late.send(0.30)[1][0].explained is None


def test_a_change_in_the_wrong_direction_is_not_explained():
    feed = flooded_feed()
    expect(feed, direction=-1)

    _, found = feed.send(2.5)

    assert found and found[0].explained is None and found[0].doubted


def test_another_zone_or_another_kind_of_sensor_is_not_explained():
    feed = flooded_feed()
    expect(feed, zone="zone-09")
    other = flooded_feed()
    expect(other, sensor_type="power_load")

    assert feed.send(0.30)[1][0].explained is None
    assert other.send(0.30)[1][0].explained is None


def test_a_distrusted_reading_is_never_explained():
    feed = flooded_feed()
    expect(feed)

    _, found = feed.send(0.30, trusted=False)

    assert found and found[0].explained is None and not found[0].trusted


def test_an_explained_change_does_not_excuse_a_spike_that_goes_the_other_way_afterwards():
    feed = flooded_feed()
    expect(feed)
    feed.send(0.30)

    _, found = feed.send(2.8)

    assert found and found[0].explained is None and found[0].doubted


# --- the sink that turns executed actions into expectations -----------------------------------------------------------


def event(kind, **data):
    return TimelineEvent(type=kind, subject="inc-0001", traceid="wl-01-01:1", data=data)


def wire(world):
    models = ForwardModels(ForwardPolicy())
    world.reading("wl-01-01", "water_level", "zone-01", {"level_m": 1.2}, 5)
    return models, ActionEffects(EFFECTS, world.store, models)


def requested(action="set_valve_state", **params):
    return event("brain.action.requested", decision_id="d1", actuator_id="valve-01-01", action=action,
                 params={"valve_id": "valve-01-01", "state": "closed", **params}, trust_ref="verdict-0001")


def test_an_executed_action_with_a_declared_effect_becomes_an_expectation_in_its_zone(world):
    models, sink = wire(world)

    sink.write(requested())
    sink.write(event("brain.action.result", decision_id="d1", status="set"))

    assert len(models._expected) == 1
    expectation = models._expected[0]
    assert expectation.zone == "zone-01" and expectation.sensor_type == "water_level" and expectation.direction == -1
    assert expectation.start == T0 + timedelta(seconds=5) and expectation.end == T0 + timedelta(seconds=65)


def test_an_action_the_twin_refused_or_that_failed_expects_nothing(world):
    models, sink = wire(world)

    sink.write(requested())
    sink.write(event("brain.action.result", decision_id="d1", status="error"))

    assert models._expected == []


def test_an_action_without_a_declared_effect_expects_nothing(world):
    models, sink = wire(world)

    sink.write(requested(action="broadcast_alert"))
    sink.write(event("brain.action.result", decision_id="d1", status="broadcast"))

    assert models._expected == []


def test_a_zone_comes_from_the_params_when_they_name_one(world):
    models, sink = wire(world)

    sink.write(event("brain.action.requested", decision_id="d2", actuator_id="x", action="set_valve_state",
                     params={"zone_id": "zone-04"}, trust_ref="v"))
    sink.write(event("brain.action.result", decision_id="d2", status="set"))

    assert models._expected[0].zone == "zone-04"


def test_expectations_that_have_ended_are_dropped(world):
    models, sink = wire(world)
    sink.write(requested())
    sink.write(event("brain.action.result", decision_id="d1", status="set"))
    feed = Feed(models)

    feed.calm(100)  # readings at T0 + 1 s ... T0 + 100 s: past the end of the window

    assert models._expected == []


def test_every_field_an_effect_names_is_expected_in_its_own_direction(world):
    models = ForwardModels(ForwardPolicy())
    world.reading("tcam-05-01", "traffic_camera", "zone-05", {"congestion_score": 0.9, "vehicle_count": 40, "avg_speed_kmh": 4.0}, 5)
    effects = {"set_signal_phase": Effect(sensor_type="traffic_camera", changes={"congestion_score": -1, "avg_speed_kmh": 1}, window_s=30)}
    sink = ActionEffects(effects, world.store, models)

    sink.write(TimelineEvent(type="brain.action.requested", traceid="tcam-05-01:1", data={
        "decision_id": "d1", "action": "set_signal_phase", "params": {"intersection_id": "sig-05-01", "phase": "green"}}))
    sink.write(TimelineEvent(type="brain.action.result", data={"decision_id": "d1", "status": "set"}))

    assert {(e.field, e.direction, e.zone) for e in models._expected} == {("congestion_score", -1, "zone-05"), ("avg_speed_kmh", 1, "zone-05")}
