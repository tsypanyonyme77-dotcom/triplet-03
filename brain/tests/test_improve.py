"""`brain improve`: nothing is applied unless every check passes, and not without --apply."""

from pathlib import Path
from types import SimpleNamespace

from brain.mind.improve import Check, improve, markdown

PROPOSAL = {"path": "forward.z_threshold", "from": 4.0, "to": 3.75, "design_gain": 0.2, "held_out_gain": 0.2}


def run(tmp_path, *, apply, proposals=(PROPOSAL,), checks=(Check("baseline", True),)):
    calls = []

    async def measure():
        return {"loss": 1.0}

    async def propose(dry):
        calls.append(dry)
        return SimpleNamespace(promoted=list(proposals), rejected=[])

    async def verify():
        return list(checks)

    import asyncio

    return asyncio.run(improve(Path(tmp_path), apply=apply, measure=measure, propose=propose, verify=verify)), calls


def test_without_apply_nothing_is_written_except_the_report(tmp_path):
    result, calls = run(tmp_path, apply=False)

    assert calls == [True] and not result.applied and "--apply" in result.note


def test_a_proposal_that_fails_any_verification_is_not_applied(tmp_path):
    result, calls = run(tmp_path, apply=True, checks=[Check("baseline", True), Check("red team", False, "1 attack got through")])

    assert calls == [True] and not result.applied and "failed" in result.note


def test_no_proposal_is_a_valid_result(tmp_path):
    result, calls = run(tmp_path, apply=True, proposals=())

    assert calls == [True] and not result.applied and "no proposal" in result.note


def test_with_apply_and_every_check_passing_the_overlay_is_written(tmp_path):
    result, calls = run(tmp_path, apply=True)

    assert calls == [True, False] and result.applied


def test_the_report_lists_every_check_with_its_result(tmp_path):
    result, _ = run(tmp_path, apply=False, checks=[Check("baseline", True, "no differences"), Check("red team", False, "x")])
    text = markdown("2026-11-05", result)

    assert "PASS baseline" in text and "FAIL red team" in text and "forward.z_threshold" in text
