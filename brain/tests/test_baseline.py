"""The baseline harness: what the Brain decided on each Test Book scenario, kept so later changes can be compared."""

import copy

from brain.baseline import differences, measure


async def test_measuring_b2_reports_the_pursuit_decision():
    result = await measure("d3")

    assert result["passed"]
    dispatches = [d for d in result["decisions"] if d["action"] == "dispatch_unit"]
    assert "pursuit" in [d["params"]["mode"] for d in dispatches]
    assert result["first_action_ms"] is not None


async def test_a_calm_day_has_no_decisions_and_no_first_action():
    result = await measure("d1")

    assert result["decisions"] == []
    assert result["first_action_ms"] is None
    assert result["readings"] == 6


async def test_differences_ignore_timings_but_catch_a_changed_decision():
    saved = {"d3": await measure("d3")}

    retimed = copy.deepcopy(saved)
    retimed["d3"]["first_action_ms"] = 9999.0
    retimed["d3"]["events"] += 7
    assert differences(saved, retimed) == []

    changed = copy.deepcopy(saved)
    changed["d3"]["decisions"][0]["params"]["zone_id"] = "zone-99"
    lines = differences(saved, changed)
    assert len(lines) == 1
    assert "d3" in lines[0] and "decisions" in lines[0]


