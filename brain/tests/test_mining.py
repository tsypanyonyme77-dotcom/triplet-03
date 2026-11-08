"""Mining: a plan the team made the same way more than once is a candidate lesson. Counting, no model."""

import json
import re

from brain.mind.episodes import Episode, IncidentRef, PlanAction, PlanRecord, Pursuit
from brain.mind.sleep import mine

CONTAIN_04 = PlanAction(action="dispatch_unit", params={"unit_type": "police", "zone_id": "zone-04", "mode": "contain"})
CONTAIN_08 = PlanAction(action="dispatch_unit", params={"unit_type": "police", "zone_id": "zone-08", "mode": "contain"})
ALERT = PlanAction(action="broadcast_alert", params={"message": "Police activity in Downtown. Please avoid the area.", "channel": "app", "zone_id": "zone-07"})


def episode(n, actions=(CONTAIN_04, CONTAIN_08, ALERT), zone="zone-07", pursuit="zone-07", heading="zone-08", type="crime"):
    return Episode(
        episode_id=f"ep-{n}", incident=IncidentRef(type=type, zone_id=zone), readings=[],
        pursuits=[Pursuit(zone_id=pursuit, heading_zone_id=heading)], plans=[PlanRecord(reason="plan", actions=list(actions))],
        team_runs=1, outcome="apprehended",
    )


def test_two_episodes_with_the_same_plan_make_one_candidate():
    (candidate,) = mine([episode(1), episode(2)], min_support=2)

    assert candidate.signature == ("zone-07", "zone-07", "zone-08") and candidate.sources == ["ep-1", "ep-2"]
    rule = candidate.rule
    assert rule["scope"] == "plan" and rule["learned"] == {"sources": ["ep-1", "ep-2"], "support": 2}
    assert rule["when"] == {"incident.type": "crime", "incident.zone_id": "zone-07", "assessment.level": "suspect",
                            "assessment.last_zone_id": "zone-07", "assessment.heading_zone_id": "zone-08"}
    assert [(d["action"], d["params"].get("mode"), d["params"]["zone_id"]) for d in rule["do"]] == [
        ("dispatch_unit", "contain", "zone-04"), ("dispatch_unit", "contain", "zone-08"), ("broadcast_alert", None, "zone-07")]
    assert rule["do"][0]["params"]["target_id"] == "$assessment.entity_id" and rule["do"][0]["params"]["incident_id"] == "$incident.incident_id"


def test_one_episode_is_not_a_lesson():
    assert mine([episode(1)], min_support=2) == []


def test_two_different_plans_for_the_same_signature_make_no_candidate_on_a_tie():
    assert mine([episode(1), episode(2, actions=(CONTAIN_04, ALERT))], min_support=1) == []


def test_the_more_common_plan_wins_when_there_is_no_tie():
    candidates = mine([episode(1), episode(2), episode(3, actions=(CONTAIN_04, ALERT))], min_support=2)

    assert len(candidates) == 1 and candidates[0].sources == ["ep-1", "ep-2"]


def test_a_plan_with_a_pursuit_or_recall_is_never_a_candidate():
    pursuit = PlanAction(action="dispatch_unit", params={"unit_type": "police", "zone_id": "zone-08", "mode": "pursuit"})
    recall = PlanAction(action="recall_unit", params={})
    valve = PlanAction(action="set_valve_state", params={"state": "closed"})

    for bad in (pursuit, recall, valve):
        assert mine([episode(1, actions=(CONTAIN_04, bad)), episode(2, actions=(CONTAIN_04, bad))], min_support=2) == []


def test_the_candidate_names_no_person_and_no_unit():
    (candidate,) = mine([episode(1), episode(2)], min_support=2)

    text = json.dumps(candidate.rule)
    assert "cit-" not in text and "unit-" not in text and not re.search(r"\bp-\d+\b", text)


def test_different_signatures_are_mined_separately():
    other = (CONTAIN_08, ALERT)
    candidates = mine([episode(1), episode(2), episode(3, actions=other, heading="zone-04"), episode(4, actions=other, heading="zone-04")], min_support=2)

    assert sorted(c.signature for c in candidates) == [("zone-07", "zone-07", "zone-04"), ("zone-07", "zone-07", "zone-08")]


def test_only_crime_episodes_with_exactly_one_pursuit_are_mined():
    jam = Episode(episode_id="ep-j", incident=IncidentRef(type="jam", zone_id="zone-05"), readings=[], outcome="cleared")
    two = episode(5)
    two.pursuits.append(Pursuit(zone_id="zone-08"))

    assert mine([jam, jam, two, two], min_support=2) == []


def test_an_episode_flagged_untrusted_or_retracted_is_left_out_by_the_caller_not_mined_here():
    # mining counts what it is given; provenance is a promotion check (see test_sleep), so a lesson cannot hide there
    assert len(mine([episode(1), episode(2)], min_support=2)) == 1
