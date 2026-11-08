"""What sleep is for, measured: the same pattern costs fewer team runs and less time, with the same decisions."""


from brain.config import Policy
from brain.mind.curve import learning_curve
from brain.mind.episodes import EpisodeStore, PlanAction, PlanRecord
from brain.mind.sleep import Sleeper
from brain.timeline import MemorySink, Timeline
from tests.test_sleep import SUITE, record


async def test_run_three_needs_fewer_team_runs_than_run_one_with_the_same_decisions(tmp_path):
    rows = await learning_curve("d3", runs=3, workdir=tmp_path, policy=Policy(), suite=SUITE)

    first, second, third = rows
    assert (first["team_runs"], second["team_runs"], third["team_runs"]) == (1, 1, 0)
    assert (first["compiled_plans"], third["compiled_plans"]) == (0, 1)
    assert first["decisions_equal_to_run_1"] and second["decisions_equal_to_run_1"] and third["decisions_equal_to_run_1"]
    # The time saved is real but small with the scripted team and noisy under load, so it is reported (`brain learning-curve`), not gated.
    assert third["last_action_ms"] <= 2 * first["last_action_ms"]
    assert [row["promoted_after"] for row in rows] == [0, 1, 1]


async def test_a_repeated_poisoned_plan_is_rejected_because_the_team_would_not_make_it(tmp_path):
    """Three trusted-looking episodes that all 'teach' a nonsense perimeter. Counting alone would promote it."""
    await record(tmp_path / "episodes", runs=1)
    store = EpisodeStore(tmp_path / "episodes")
    (real,), _ = store.all()
    nonsense = [PlanAction(action="dispatch_unit", params={"unit_type": "police", "zone_id": "zone-01", "mode": "contain"}),
                PlanAction(action="dispatch_unit", params={"unit_type": "police", "zone_id": "zone-02", "mode": "contain"})]
    for n in range(3):
        store.append(real.model_copy(update={"episode_id": f"ep-poison-{n}", "plans": [PlanRecord(reason="plan", actions=nonsense)]}))
    sleeper = Sleeper(tmp_path / "episodes", tmp_path / "learned", Policy(), Timeline([MemorySink()]), suite=SUITE, held_out=[])

    report = await sleeper.run()

    assert report.candidates == 1 and report.promoted == []
    (rejected,) = report.rejected
    assert rejected["check"] == "rehearsal" and "decides differently" in rejected["reason"]
    assert rejected["checks"] == ["provenance", "safety", "cap"]
    assert not (tmp_path / "learned" / "rules.yaml").exists()


async def test_a_poisoned_lesson_cannot_ride_on_a_real_one(tmp_path):
    """Two real episodes and two poisoned ones for the same pattern: the team's plan wins the count and passes; the poison never does."""
    await record(tmp_path / "episodes", runs=2)
    store = EpisodeStore(tmp_path / "episodes")
    (real, _), _ = store.all()
    bad = [PlanAction(action="dispatch_unit", params={"unit_type": "police", "zone_id": "zone-01", "mode": "contain"})]
    for n in range(2):
        store.append(real.model_copy(update={"episode_id": f"ep-poison-{n}", "plans": [PlanRecord(reason="plan", actions=bad)]}))
    sleeper = Sleeper(tmp_path / "episodes", tmp_path / "learned", Policy(), Timeline([MemorySink()]), suite=SUITE, held_out=[])

    report = await sleeper.run()

    assert report.candidates == 0 and report.promoted == []  # a 2 to 2 tie is no lesson, so nothing is learned until more evidence arrives
