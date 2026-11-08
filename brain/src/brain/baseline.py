"""Baseline harness: what the Brain does on the Test Book, recorded so later changes can be compared.

Each scenario runs the way the test suite runs it (scripted team, in-process mocks, no waiting,
hashing embeddings), so a number here is the same on every machine. Decisions and refusals are
the part that must never drift; counts and timings are for reading, not for comparing.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from typing import Any

from brain import config
from brain.config import ModelsConfig, PartnersConfig, Policy
from brain.contracts.signing import canonical_json
from brain.mind.funnel import funnel
from brain.scenario import DEV_SECRETS, inproc_partners, load_scenario, run_scenario

MODELS = ModelsConfig.model_validate({"embeddings": {"provider": "hashing"}})
COMPARED = ("passed", "decisions", "blocked")


def _scenario_number(scenario_id: str) -> int:
    return int(re.sub(r"\D", "", scenario_id) or 0)


def _canonical(value: Any) -> str:
    return canonical_json(value).decode()


async def measure(scenario_id: str, policy: Policy | None = None, partners: PartnersConfig | None = None) -> dict[str, Any]:
    """Run one Test Book scenario and summarise what the Brain read, decided and refused."""
    return await measure_scenario(load_scenario(scenario_id), policy, partners)


async def measure_scenario(
    scenario: dict[str, Any], policy: Policy | None = None, partners: PartnersConfig | None = None,
    models: ModelsConfig | None = None, llm_crew: Any = None, speed: float = 0, timeout_s: float = 20,
) -> dict[str, Any]:
    """The same for a scenario already in hand (sleep rehearses replayed episodes this way)."""
    for name, value in DEV_SECRETS.items():
        os.environ.setdefault(name, value)
    result = await run_scenario(scenario, inproc_partners(), partners=partners, policy=policy, models=models or MODELS, speed=speed, timeout_s=timeout_s, llm_crew=llm_crew)
    sink = result.sink

    decisions = sorted(
        ({"action": e.data["action"], "actuator_id": e.data["actuator_id"], "params": e.data["params"]}
         for e in sink.of("brain.decision.made")),
        key=_canonical,
    )
    opened = sink.of("brain.incident.opened")
    acted = sink.of("brain.action.result")
    first_action_ms = last_action_ms = None
    if opened and acted:
        first_action_ms = round((acted[0].time - opened[0].time).total_seconds() * 1000, 1)
        last_action_ms = round((acted[-1].time - opened[0].time).total_seconds() * 1000, 1)
    return {
        "scenario_id": scenario["id"],
        "passed": result.passed,
        "readings": len(sink.of("brain.reading.received")),
        "events": len(sink.events),
        "deliberations": len(sink.of("brain.deliberation.started")),
        "compiled_plans": len(sink.of("brain.plan.compiled")),
        "decisions": decisions,
        "blocked": sorted(e.data.get("check", "") for e in sink.of("brain.action.blocked")),
        "first_action_ms": first_action_ms,
        "last_action_ms": last_action_ms,
        "funnel": funnel(sink.events),
        "event_counts": dict(Counter(e.type for e in sink.events)),
    }


def _all_scenario_ids() -> list[str]:
    folder = config.home() / "scenarios"
    return sorted((p.stem for p in folder.glob("t*.json")), key=_scenario_number)


# Every solver off: the pipeline as it decided before 6 Nov, so the older frozen baselines can still be checked.
PLAIN_SETS = ["optimiser.dispatch=off", "optimiser.shed=off", "optimiser.perimeter=off", "math.kalman=off", "math.prewarn_s=0", "orchestration.planner=off"]


async def measure_all(
    ids: list[str] | None = None, policy: Policy | None = None, partners: PartnersConfig | None = None
) -> dict[str, dict[str, Any]]:
    return {scenario_id: await measure(scenario_id, policy, partners) for scenario_id in (ids or _all_scenario_ids())}


def differences(saved: dict[str, dict[str, Any]], current: dict[str, dict[str, Any]]) -> list[str]:
    """One line per scenario field that changed. Timings and counts are ignored on purpose."""
    lines = []
    for scenario_id in sorted(saved, key=_scenario_number):
        if scenario_id not in current:
            lines.append(f"{scenario_id}: missing from the current run")
            continue
        for key in COMPARED:
            if saved[scenario_id].get(key) != current[scenario_id].get(key):
                lines.append(f"{scenario_id}: {key} changed from {_canonical(saved[scenario_id].get(key))} "
                             f"to {_canonical(current[scenario_id].get(key))}")
    return lines


def dump(results: dict[str, dict[str, Any]]) -> str:
    return json.dumps(results, indent=2, sort_keys=True) + "\n"
