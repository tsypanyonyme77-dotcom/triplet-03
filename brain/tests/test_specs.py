"""Temporal specifications over the timeline: what the Brain promises across time, checked on its own log, with no model."""

import json

import pytest

from brain.contracts import TimelineEvent
from brain.mind.specs import SPECS, read_log, verify_log
from brain.scenario import load_scenario
from tests.test_scenarios import play


def ev(kind, subject=None, **data):
    return TimelineEvent(type=kind, subject=subject, data=data)


def verdict(reading="s#1", vid="v-1", status="trusted"):
    return ev("brain.verdict.received", reading, verdict_id=vid, status=status)


def decision(did="d-1"):
    return ev("brain.decision.made", "inc-1", decision_id=did)


def request(did="d-1", trust="v-1", action="dispatch_unit", incident="inc-1", **params):
    return ev("brain.action.requested", incident, decision_id=did, action=action, trust_ref=trust, params={"incident_id": incident, **params})


def result(did="d-1", status="dispatched", **extra):
    return ev("brain.action.result", "inc-1", decision_id=did, status=status, **extra)


CLEAN = [verdict(), decision(), request(mode="pursuit", target_id="t-1"), result(unit_id="u-1"),
         ev("brain.incident.closed", "inc-1", outcome="apprehended"),
         ev("brain.units.released", "inc-1", cause="closed", units=[{"unit_id": "u-1"}])]


def broken(events):
    return {violation.spec for violation in verify_log(events)}


def test_a_clean_log_breaks_no_specification():
    assert verify_log(CLEAN) == []


def test_every_specification_has_an_id_and_a_plain_description():
    assert set(SPECS) == {f"TS-0{n}" for n in range(1, 8)}
    assert all(spec.description and len(spec.description) < 160 for spec in SPECS.values())


def test_ts01_an_action_on_a_verdict_that_was_not_trusted_is_caught():
    log = [verdict(status="untrusted"), decision(), request(), result()]

    assert "TS-01" in broken(log)


def test_ts01_an_action_that_cites_a_verdict_no_one_gave_is_caught():
    assert "TS-01" in broken([decision(), request(trust="v-ghost"), result()])


def test_ts02_a_request_without_a_decision_is_caught():
    assert "TS-02" in broken([verdict(), request(), result()])


def test_ts03_a_request_that_is_never_answered_is_caught():
    assert "TS-03" in broken([verdict(), decision(), request()])


def test_ts04_an_action_after_the_incident_closed_is_caught_but_a_recall_is_not():
    closed = ev("brain.incident.closed", "inc-1", outcome="cleared")
    late = [verdict(), closed, decision("d-2"), request("d-2"), result("d-2")]
    recall = [verdict(), closed, decision("d-2"), request("d-2", action="recall_unit"), result("d-2", status="recalled")]

    assert "TS-04" in broken(late) and "TS-04" not in broken(recall)


def test_ts05_an_action_citing_a_retracted_verdict_is_caught():
    log = [verdict(), ev("brain.evidence.retracted", "s#1", reading_id="s#1", reason="x"), decision(), request(), result()]

    assert "TS-05" in broken(log)


def test_ts05_an_action_before_the_retraction_is_fine():
    log = [verdict(), decision(), request(), result(), ev("brain.evidence.retracted", "s#1", reading_id="s#1", reason="x")]

    assert "TS-05" not in broken(log)


def test_ts06_a_second_pursuit_of_a_target_still_being_chased_is_caught():
    log = [verdict(), decision(), request(mode="pursuit", target_id="t-1"), result(unit_id="u-1"),
           decision("d-2"), request("d-2", mode="pursuit", target_id="t-1"), result("d-2", unit_id="u-2")]

    assert "TS-06" in broken(log)


def test_ts06_a_new_pursuit_after_the_first_unit_came_home_is_fine():
    log = [verdict(), decision(), request(mode="pursuit", target_id="t-1"), result(unit_id="u-1"),
           ev("brain.units.released", "inc-1", cause="x", units=[{"unit_id": "u-1"}]),
           decision("d-2"), request("d-2", mode="pursuit", target_id="t-1"), result("d-2", unit_id="u-2")]

    assert "TS-06" not in broken(log)


def test_ts07_a_unit_that_never_comes_home_is_caught_only_when_the_run_is_complete():
    log = [verdict(), decision(), request(mode="pursuit", target_id="t-1"), result(unit_id="u-1")]

    assert "TS-07" in broken(log)
    assert "TS-07" not in {v.spec for v in verify_log(log, complete=False)}


def test_a_violation_says_which_event_and_why():
    (violation,) = [v for v in verify_log([verdict(), request(), result()]) if v.spec == "TS-02"]

    assert violation.index == 1 and "d-1" in violation.message


def test_a_log_file_can_be_read_back_and_checked(tmp_path):
    path = tmp_path / "run.jsonl"
    path.write_text("\n".join(json.dumps(e.model_dump(mode="json")) for e in CLEAN) + "\n")

    assert verify_log(read_log(path)) == []


@pytest.mark.parametrize("scenario_id", ["t12", "t13", "t14", "t15"])
async def test_every_scenario_keeps_every_promise(scenario_id):
    result_ = await play(load_scenario(scenario_id))

    assert verify_log(result_.sink.events) == [], scenario_id
