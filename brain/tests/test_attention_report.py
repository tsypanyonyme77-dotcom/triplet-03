"""The attention report: where the workspace's slots and the team's runs went, counted from the timeline."""

from brain.contracts import TimelineEvent
from brain.mind.attention_report import attention_report


def ev(kind, subject=None, **data):
    return TimelineEvent(type=kind, subject=subject, data=data)


def reading():
    return ev("brain.reading.received", "s#1")


def test_a_lit_incident_waits_the_readings_between_opening_and_a_slot():
    events = [reading(), ev("brain.incident.opened", "inc-1", type="crime"), reading(), reading(),
              ev("brain.workspace.ignited", "inc-1", type="crime", salience=0.7, slots=["inc-1"])]

    report = attention_report(events)

    assert report["incidents"]["inc-1"]["waited_readings"] == 2 and report["lit"] == 1 and report["denied"] == 0


def test_an_incident_that_was_deferred_and_never_lit_is_denied_and_waits_to_the_end():
    events = [ev("brain.incident.opened", "inc-1", type="crime"), reading(),
              ev("brain.workspace.deferred", "inc-1", salience=0.7, holding=["inc-0"]), reading(), reading()]

    report = attention_report(events)

    assert report["denied"] == 1 and report["incidents"]["inc-1"]["lit_at"] is None
    assert report["longest_wait_readings"] == 2  # from the first deferral to the end of the run


def test_an_incident_that_never_reached_the_bar_is_neither_lit_nor_denied():
    events = [ev("brain.incident.opened", "inc-1", type="jam"), reading()]

    report = attention_report(events)

    assert report["denied"] == 0 and report["below_the_bar"] == 1


def test_a_slot_given_to_a_type_with_no_team_is_counted_and_a_slotless_light_is_not():
    events = [ev("brain.incident.opened", "inc-1", type="flood"), ev("brain.workspace.ignited", "inc-1", type="flood", salience=0.7, slots=["inc-1"]),
              ev("brain.incident.opened", "inc-2", type="fire"), ev("brain.workspace.ignited", "inc-2", type="fire", salience=0.9, slots=["inc-1"], slot=False)]

    report = attention_report(events)

    assert report["slots_on_teamless"] == 1 and report["lit"] == 2


def test_an_incident_deferred_while_better_than_a_lit_one_is_an_inversion():
    events = [ev("brain.incident.opened", "inc-1", type="crime"), ev("brain.workspace.ignited", "inc-1", type="crime", salience=0.6, slots=["inc-1"]),
              ev("brain.incident.opened", "inc-2", type="crime"), ev("brain.workspace.deferred", "inc-2", salience=0.65, holding=["inc-1"])]

    assert attention_report(events)["inversions"] == 1


