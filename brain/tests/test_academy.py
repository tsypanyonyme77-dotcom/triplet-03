"""The Academy: bounded self-improvement. It proposes one step at a time, inside the surface, and promotes only through a gate."""

import json

from brain.config import Policy
from brain.mind.academy import Academy, Battery, Evaluation, audit, rollback, show
from brain.mind.surface import SURFACE, load_overlay


class FakeBattery:
    """A battery whose loss the test controls. `design` and `held` are functions of the policy; `fails` names a constraint."""

    def __init__(self, design, held=None, fails=lambda policy: None):
        self.design_fn, self.held_fn, self.fails = design, held or design, fails
        self.seen: list[Policy] = []

    async def design(self, policy):
        self.seen.append(policy)
        return Evaluation(self.design_fn(policy), {})

    async def held_out(self, policy):
        return Evaluation(self.held_fn(policy), {})

    async def constraints(self, policy):
        failed = self.fails(policy)
        return {"decisions": (failed is None, failed or "every decision as before")}


def margin_loss(optimum):
    return lambda policy: 1.0 + abs(policy.workspace.margin - optimum) * 100


async def test_a_change_that_helps_on_both_sets_and_breaks_nothing_is_promoted_step_by_step(tmp_path):
    academy = Academy(tmp_path, FakeBattery(margin_loss(0.15)))

    report = await academy.run(steps=10)

    overlay, problem = load_overlay(tmp_path)
    assert overlay == {"workspace.margin": 0.15} and problem is None
    assert [p["path"] for p in report.promoted] == ["workspace.margin"] * 2  # 0.10 -> 0.125 -> 0.15
    assert report.promoted[-1]["to"] == 0.15 and report.promoted[-1]["design_gain"] > 0 and report.promoted[-1]["held_out_gain"] > 0


async def test_it_stops_when_a_whole_pass_finds_nothing_better(tmp_path):
    academy = Academy(tmp_path, FakeBattery(margin_loss(0.10)))

    report = await academy.run(steps=10)

    assert report.promoted == [] and load_overlay(tmp_path) == ({}, None)


async def test_a_change_that_helps_on_the_design_set_and_hurts_on_the_held_out_set_is_rejected(tmp_path):
    battery = FakeBattery(margin_loss(0.15), held=margin_loss(0.05))

    report = await Academy(tmp_path, battery).run(steps=5)

    assert report.promoted == [] and report.rejected and report.rejected[0]["check"] == "held-out"


async def test_a_change_that_breaks_a_constraint_is_rejected_whatever_it_gains(tmp_path):
    battery = FakeBattery(margin_loss(0.15), fails=lambda policy: "decision moved" if policy.workspace.margin > 0.1 else None)

    report = await Academy(tmp_path, battery).run(steps=5)

    assert report.promoted == [] and report.rejected[0]["check"] == "decisions" and "decision moved" in report.rejected[0]["reason"]


async def test_a_gain_smaller_than_the_minimum_is_not_worth_a_change(tmp_path):
    battery = FakeBattery(lambda policy: 100.0 + abs(policy.workspace.margin - 0.125) * 0.001)

    report = await Academy(tmp_path, battery, min_gain=0.005).run(steps=5)

    assert report.promoted == []


async def test_the_overlay_never_holds_more_than_the_allowed_number_of_changes(tmp_path):
    def wants_everything(policy):
        w = policy.workspace
        return 10 + abs(w.margin - 0.2) * 50 + abs(w.ignite_at - 0.4) * 50 + abs(w.release_below - 0.4) * 50

    await Academy(tmp_path, FakeBattery(wants_everything), max_changes=2).run(steps=30)

    overlay, _ = load_overlay(tmp_path)
    assert 0 < len(overlay) <= 2


async def test_it_only_ever_tries_values_on_the_surface_and_one_step_from_where_it_is(tmp_path):
    battery = FakeBattery(margin_loss(0.2))
    await Academy(tmp_path, battery).run(steps=3)

    base = Policy()
    for policy in battery.seen:
        for path, tunable in SURFACE.items():
            node = policy
            for part in path.split("."):
                node = node[part] if isinstance(node, dict) else getattr(node, part)
            assert tunable.low - 1e-9 <= node <= tunable.high + 1e-9


async def test_the_same_run_twice_gives_the_same_overlay(tmp_path):
    first, second = tmp_path / "a", tmp_path / "b"

    await Academy(first, FakeBattery(margin_loss(0.175))).run(steps=10)
    await Academy(second, FakeBattery(margin_loss(0.175))).run(steps=10)

    assert load_overlay(first) == load_overlay(second) != ({}, None)


async def test_a_dry_run_writes_nothing(tmp_path):
    report = await Academy(tmp_path, FakeBattery(margin_loss(0.15))).run(steps=5, dry_run=True)

    assert report.promoted and not (tmp_path / "overlay.yaml").exists() and not (tmp_path / "history.jsonl").exists()


async def test_every_promotion_and_rejection_is_in_the_history_with_its_evidence(tmp_path):
    await Academy(tmp_path, FakeBattery(margin_loss(0.15), held=margin_loss(0.125))).run(steps=6)

    lines = [json.loads(line) for line in (tmp_path / "history.jsonl").read_text().splitlines()]
    assert {line["action"] for line in lines} <= {"promoted", "rejected"}
    assert all({"path", "from", "to", "design_gain", "at"} <= set(line) for line in lines)


# --- rollback, show and the self-audit ------------------------------------------------------------------------------


async def test_a_rollback_removes_a_parameter_and_the_brain_is_exactly_what_it_was(tmp_path):
    await Academy(tmp_path, FakeBattery(margin_loss(0.15))).run(steps=5)

    gone = rollback(tmp_path, "workspace.margin")

    assert gone == ["workspace.margin"] and load_overlay(tmp_path) == ({}, None)
    actions = [json.loads(line)["action"] for line in (tmp_path / "history.jsonl").read_text().splitlines()]
    assert "promoted" in actions and actions[-1] == "rolled back"


async def test_a_rollback_of_everything_empties_the_overlay(tmp_path):
    await Academy(tmp_path, FakeBattery(margin_loss(0.15))).run(steps=5)

    assert rollback(tmp_path, "all") == ["workspace.margin"]
    assert rollback(tmp_path, "all") == []


async def test_show_lists_the_overlay_with_the_evidence_for_each_value(tmp_path):
    await Academy(tmp_path, FakeBattery(margin_loss(0.15))).run(steps=5)

    text = show(tmp_path)

    assert "workspace.margin" in text and "0.15" in text and "gain" in text


async def test_the_audit_keeps_a_change_that_still_helps_on_new_stories_and_retires_one_that_does_not(tmp_path):
    await Academy(tmp_path, FakeBattery(margin_loss(0.15))).run(steps=5)

    kept = await audit(tmp_path, FakeBattery(margin_loss(0.15)))
    retired = await audit(tmp_path, FakeBattery(margin_loss(0.05)))

    assert kept == [] and retired == ["workspace.margin"] and load_overlay(tmp_path) == ({}, None)


# --- the real battery -------------------------------------------------------------------------------------------------


async def test_the_untuned_policy_has_a_stable_loss_and_keeps_every_constraint():
    battery = Battery()

    first, second = await battery.design(Policy()), await battery.design(Policy())  # the frozen baseline is the Brain as it ships
    constraints = await battery.constraints(Policy())

    assert first.loss == second.loss > 0
    assert all(ok for ok, _ in constraints.values()), constraints


async def test_a_policy_too_deaf_to_see_small_anomalies_fails_the_recall_constraint():
    constraints = await Battery().constraints(Policy.model_validate({"forward": {"z_threshold": 5.5}}))

    assert not constraints["recall"][0]
