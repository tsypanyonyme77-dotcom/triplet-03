"""The learning curve: the same scenario, run again and again, with sleep in between.

It exists to put a number on what quiet-time learning buys: team runs and time to a complete response should fall
between run 1 and run 3, while the decisions stay exactly the same.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from brain.baseline import measure_scenario
from brain.config import BrainConfig, PartnersConfig, Policy
from brain.mind.sleep import sleep
from brain.scenario import load_scenario
from brain.timeline import MemorySink, Timeline


async def learning_curve(
    scenario_id: str, runs: int, workdir: Path, policy: Policy, suite: list[str] | None = None, sleep_after: int = 2,
) -> list[dict[str, Any]]:
    """Run the scenario `runs` times, recording episodes; sleep once after run `sleep_after`. One row per run."""
    episodes, learned = workdir / "episodes", workdir / "learned"
    partners = PartnersConfig(brain=BrainConfig(episodes_dir=str(episodes), learned_dir=str(learned)))
    rows: list[dict[str, Any]] = []
    first: list[dict[str, Any]] | None = None
    promoted = 0
    for number in range(1, runs + 1):
        result = await measure_scenario(load_scenario(scenario_id), policy, partners)
        first = first if first is not None else result["decisions"]
        rows.append({
            "run": number, "team_runs": result["deliberations"], "compiled_plans": result["compiled_plans"],
            "first_action_ms": result["first_action_ms"], "last_action_ms": result["last_action_ms"],
            "decisions_equal_to_run_1": result["decisions"] == first, "promoted_after": 0,
        })
        if number == sleep_after:
            report = await sleep(episodes, learned, policy, Timeline([MemorySink()]), suite=suite, held_out=[])
            promoted = len(report.promoted)
        rows[-1]["promoted_after"] = promoted
    return rows


def dump(rows: list[dict[str, Any]]) -> str:
    return json.dumps(rows, indent=2) + "\n"
