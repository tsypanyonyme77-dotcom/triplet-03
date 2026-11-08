"""The life of a lesson: confirmed when its pattern recurs, faded when it stops, retired when the team later plans it differently."""

import copy

from brain.config import LearningPolicy
from brain.mind.episodes import Episode, IncidentRef, Pursuit
from brain.mind.lifecycle import review
from brain.mind.sleep import mine
from tests.test_mining import ALERT, CONTAIN_04, episode

POLICY = LearningPolicy(fade_after_sleeps=2)


def rule_from(*episodes):
    (candidate,) = mine(list(episodes), min_support=2)
    return {**candidate.rule, "id": "LRN-1", "learned": {**candidate.rule["learned"], "signature": list(candidate.signature), "created": "2026-10-26T00:00:00+00:00"}}


def used(n, rule_id="LRN-1"):
    """An episode of the same pattern that the learned plan answered: no team plan in it, the rule noted as used."""
    return Episode(episode_id=f"ep-{n}", incident=IncidentRef(type="crime", zone_id="zone-07"), readings=[],
                   pursuits=[Pursuit(zone_id="zone-07", heading_zone_id="zone-08")], plans=[], lessons_used=[rule_id], outcome="apprehended")


def different(n):
    return episode(n, actions=(CONTAIN_04, ALERT))


def test_a_pattern_that_recurs_keeps_its_rule_and_resets_its_idle_count():
    rule = rule_from(episode(1), episode(2))
    rule["learned"]["sleeps_idle"] = 1

    kept, retired = review([rule], [episode(1), episode(2), used(3)], POLICY)

    assert retired == [] and kept[0]["learned"]["sleeps_idle"] == 0 and kept[0]["learned"]["uses"] == 1


def test_a_team_plan_that_matches_the_rule_confirms_it():
    rule = rule_from(episode(1), episode(2))

    kept, _ = review([rule], [episode(1), episode(2), episode(3)], POLICY)

    assert kept[0]["learned"]["confirmed"] == 1 and kept[0]["learned"]["contradicted"] == 0


def test_a_rule_whose_pattern_stops_fades_after_the_set_number_of_sleeps_and_not_before():
    rule = rule_from(episode(1), episode(2))
    episodes = [episode(1), episode(2)]
    results = []
    for _ in range(3):
        kept, retired = review([rule], episodes, POLICY)
        results.append(retired)
        rule = kept[0] if kept else rule

    assert results[0] == [] and results[1] == [] and [r["check"] for r in results[2]] == ["faded"]
    assert "3 sleeps" in results[2][0]["reason"] and "limit is 2" in results[2][0]["reason"]


def test_the_default_never_fades_a_rule():
    rule = rule_from(episode(1), episode(2))
    for _ in range(20):
        kept, retired = review([rule], [episode(1), episode(2)], LearningPolicy())
        rule = kept[0]

    assert retired == [] and rule["learned"]["sleeps_idle"] == 20


def test_a_later_team_plan_that_differs_retires_the_rule_when_it_outnumbers_the_confirmations():
    rule = rule_from(episode(1), episode(2))

    kept, retired = review([rule], [episode(1), episode(2), different(3)], POLICY)

    assert kept == [] and retired[0]["check"] == "contradicted" and "ep-3" in retired[0]["reason"]


def test_one_contradiction_against_two_confirmations_does_not_retire_it():
    rule = rule_from(episode(1), episode(2))

    kept, retired = review([rule], [episode(1), episode(2), episode(3), episode(4), different(5)], POLICY)

    assert retired == [] and kept[0]["learned"]["confirmed"] == 2 and kept[0]["learned"]["contradicted"] == 1


def test_using_a_rule_never_counts_as_proof_that_it_is_right():
    rule = rule_from(episode(1), episode(2))
    episodes = [episode(1), episode(2), *[used(n) for n in range(3, 8)], different(8), different(9), episode(10)]

    kept, retired = review([rule], episodes, POLICY)

    assert [r["check"] for r in retired] == ["contradicted"], "five uses, two contradictions and one confirmation: retired"


def test_an_episode_is_counted_once_however_many_sleeps_see_it():
    rule = rule_from(episode(1), episode(2))
    episodes = [episode(1), episode(2), episode(3)]

    once, _ = review([rule], episodes, POLICY)
    twice, _ = review(once, episodes, POLICY)

    assert twice[0]["learned"]["confirmed"] == 1


def test_an_episode_of_another_pattern_does_not_touch_the_rule():
    rule = rule_from(episode(1), episode(2))
    elsewhere = episode(3, zone="zone-03", pursuit="zone-03", heading="zone-06")

    kept, retired = review([rule], [episode(1), episode(2), elsewhere], POLICY)

    assert retired == [] and kept[0]["learned"]["sleeps_idle"] == 1 and kept[0]["learned"]["confirmed"] == 0


def test_retiring_on_contradiction_can_be_switched_off():
    rule = rule_from(episode(1), episode(2))
    policy = LearningPolicy(fade_after_sleeps=2, retire_on_contradiction=False)

    kept, retired = review([rule], [episode(1), episode(2), different(3)], policy)

    assert retired == [] and kept[0]["learned"]["contradicted"] == 1


def test_the_input_rules_are_not_changed_in_place():
    rule = rule_from(episode(1), episode(2))
    before = copy.deepcopy(rule)

    review([rule], [episode(1), episode(2), episode(3)], POLICY)

    assert rule == before
