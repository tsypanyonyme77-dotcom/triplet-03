"""Reliability of the team: repeated runs, injected faults, and what the verifier and the gate let through."""

import math

import pytest

from brain.mind.specs import verify_log
from brain.reliability import FaultyCrew, pass_hat_k, trials


def test_pass_hat_k_is_the_chance_that_k_of_n_trials_all_pass():
    assert pass_hat_k(5, 5, 3) == 1.0
    assert pass_hat_k(0, 5, 1) == 0.0
    assert pass_hat_k(3, 4, 1) == pytest.approx(0.75)
    assert pass_hat_k(3, 4, 2) == pytest.approx(math.comb(3, 2) / math.comb(4, 2))
    assert pass_hat_k(3, 4, 4) == 0.0


def test_pass_hat_k_falls_as_k_grows_for_a_team_that_sometimes_fails():
    values = [pass_hat_k(8, 10, k) for k in range(1, 9)]

    assert values == sorted(values, reverse=True) and values[0] == pytest.approx(0.8)


def test_pass_hat_k_refuses_a_k_larger_than_the_number_of_trials():
    with pytest.raises(ValueError):
        pass_hat_k(2, 3, 4)


async def test_without_faults_every_trial_decides_as_the_scripted_team_does():
    rows = await trials("d3", 3, rate=0.0, seed=1)

    assert len(rows) == 3
    assert all(r["same_decisions"] and r["passed"] and r["fallbacks"] == 0 and r["rejected"] == 0 for r in rows)


async def test_when_every_role_fails_the_stand_ins_take_over_and_the_decisions_are_the_scripted_ones():
    rows = await trials("d3", 2, rate=1.0, seed=1, kinds=("error",))

    assert all(r["fallbacks"] >= 1 and r["same_decisions"] and r["passed"] for r in rows)


async def test_when_every_answer_is_garbage_the_verifier_stops_it_and_the_reflex_decisions_stand():
    rows = await trials("d3", 2, rate=1.0, seed=1, kinds=("garbage",))

    assert all(r["fewer_decisions"] for r in rows)
    assert all(r["passed"] for r in rows), "the reflex pursuit must still go out"
    assert all(not r["same_decisions"] for r in rows), "the team's perimeter must not have been placed from garbage"


async def test_a_mixture_of_faults_never_puts_an_unchecked_action_on_an_actuator():
    from brain.baseline import MODELS
    from brain.scenario import inproc_partners, load_scenario, run_scenario

    for seed in range(4):
        result = await run_scenario(load_scenario("d3"), inproc_partners(), models=MODELS, speed=0, timeout_s=30,
                                    llm_crew=FaultyCrew(0.5, seed))

        assert all(c["call"]["trust_ref"] for c in result.actuator_calls), seed
        assert verify_log(result.sink.events) == [], seed


async def test_the_same_seed_gives_the_same_faults():
    first = await trials("d3", 3, rate=0.5, seed=7)
    second = await trials("d3", 3, rate=0.5, seed=7)

    assert [(r["fallbacks"], r["rejected"], r["same_decisions"]) for r in first] == [(r["fallbacks"], r["rejected"], r["same_decisions"]) for r in second]


async def test_trials_record_what_the_team_decided_so_they_can_be_compared_with_each_other():
    from brain.reliability import summary

    rows = await trials("d3", 4, rate=0.0, seed=1)

    assert all(r["plan_placed"] for r in rows) and len({r["signature"] for r in rows}) == 1
    assert summary(rows)["plan_agreement"] == 1.0 and summary(rows)["plans_placed"] == 4


async def test_a_team_that_sometimes_places_a_different_plan_shows_it_in_the_agreement():
    from brain.reliability import summary

    rows = await trials("d3", 6, rate=0.6, seed=3, kinds=("garbage", "error"))

    assert 0 < summary(rows)["plan_agreement"] <= 1.0
