"""Ablations: switch one region off, run the Test Book, and say what it cost and what it saved."""

import tempfile
from pathlib import Path

from brain.mind.ablate import ABLATIONS, ablate, table

SUITE = ["t12", "t13", "t14", "t15"]
_result: dict | None = None


async def result() -> dict:
    """One run shared by every test in this file: an ablation pass replays the suite five times."""
    global _result
    if _result is None:
        with tempfile.TemporaryDirectory(prefix="ablate-") as folder:
            _result = await ablate(SUITE, Path(folder))
    return _result


async def test_every_region_has_a_switch_and_the_full_brain_is_the_reference():
    found = await result()

    assert list(found["configs"]) == ["full", "no workspace", "no forward models", "no bids", "no learned reflexes"]
    assert found["configs"]["full"]["decisions_changed"] == []
    assert found["configs"]["full"]["passed"] >= 3


async def test_switching_off_bids_changes_no_decision():
    found = await result()

    off = found["configs"]["no bids"]
    assert off["decisions_changed"] == [] and off["bids_reported"] == 0 and found["configs"]["full"]["bids_reported"] > 0


async def test_switching_off_learned_reflexes_brings_the_team_back():
    found = await result()

    assert found["configs"]["full"]["learned_plans_used"] >= 1 and found["configs"]["no learned reflexes"]["learned_plans_used"] == 0
    assert found["configs"]["no learned reflexes"]["team_runs"] > found["configs"]["full"]["team_runs"]
    assert found["configs"]["no learned reflexes"]["decisions_changed"] == []


async def test_the_table_reports_decisions_changed_beside_each_saving():
    text = table(await result())

    assert "decisions changed" in text and "team runs" in text
    assert all(name in text for name in ABLATIONS) 


def test_no_ablation_can_switch_the_gate_off():
    assert not any("gate" in overlay for overlay in ABLATIONS.values())
