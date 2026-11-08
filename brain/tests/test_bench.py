"""brain bench: every step reports, a failing step is shown and fails the run, and the table has a row per step."""

import asyncio
from pathlib import Path

from brain import bench


async def ok():
    return {"value": 1}


async def broken():
    raise RuntimeError("the step broke")


def run(steps):
    return asyncio.run(bench.run(steps, Path(".")))


def test_the_quick_bench_returns_every_expected_key():
    steps = bench.default_steps(Path(__file__).parents[1], quick=True)

    assert list(steps) == ["scenarios", "baselines", "dispatch", "retrieval", "forward", "conformance", "redteam"]


def test_a_failing_step_is_reported_not_swallowed_and_marks_the_run_failed():
    report = run({"fine": ok, "bad": broken})

    assert report["failures"] == ["bad"] and "the step broke" in report["results"]["bad"]["error"] and report["results"]["fine"]["value"] == 1
    assert "FAILED: bad" in bench.markdown(report)


def test_the_markdown_table_has_one_row_per_result():
    report = run({"a": ok, "b": ok, "c": ok})
    rows = [line for line in bench.markdown(report).splitlines() if line.startswith("| ") and "---" not in line and "Step" not in line]

    assert len(rows) == len(report["results"]) == 3
