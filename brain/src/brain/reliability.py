"""Reliability of the agent team: the same scenario run again and again, under faults or against the real model.

A language-model team is the one part of the Brain that is not deterministic. The scripted team plays the same roles
exactly, so it is the yardstick: a trial *passes* when the scenario's own expectations hold at the level an LLM team
is held to, and it *matches* when the decisions are the scripted team's. `FaultyCrew` stands in for the model and
fails at a chosen rate, in the ways a real one fails: an error (a timeout, a rate limit) or an answer the verifier must
reject. `pass_hat_k` is the unbiased estimate of the chance that k trials in a row all pass, the number a deployment
cares about (a team that passes 75 per cent of the time passes three in a row about 42 per cent of the time).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import random
from typing import Any

from brain.baseline import measure_scenario
from brain.config import ModelsConfig, Policy
from brain.departments.team import CaseFile, ChiefDecision, ScriptedCrew, TacticalOption, TacticalOptions, ToolBox
from brain.scenario import load_scenario

ERRORS = (TimeoutError("the model did not answer in time"), RuntimeError("429: rate limit reached for the free plan"))


class FaultyCrew:
    """Answers like the scripted team, but at `rate` per role call it fails: an error, or a garbage answer."""

    mode = "llm"

    def __init__(self, rate: float, seed: int, kinds: tuple[str, ...] = ("error", "garbage"), facility_type: str = "police_station") -> None:
        self._inner = ScriptedCrew(Policy(), facility_type)
        self._rate, self._kinds, self._rng = rate, kinds, random.Random(seed)

    def _fault(self) -> str | None:
        return self._rng.choice(self._kinds) if self._rng.random() < self._rate else None

    async def analyst(self, brief: dict[str, Any], tools: ToolBox) -> CaseFile:
        fault = self._fault()
        if fault == "error":
            raise self._rng.choice(ERRORS)
        if fault == "garbage":
            return CaseFile(recommendation="pursue", confidence="high", summary="An answer that cites nothing real.",
                            concerns=[], cited_reading_ids=["nothing#99"])
        return await self._inner.analyst(brief, tools)

    async def tactician(self, brief: dict[str, Any], tools: ToolBox) -> TacticalOptions:
        fault = self._fault()
        if fault == "error":
            raise self._rng.choice(ERRORS)
        if fault == "garbage":
            return TacticalOptions(options=[TacticalOption(name="everywhere", contain_zones=["zone-99"], alert_zones=["zone-99"], rationale="Hold a zone that does not exist.")])
        return await self._inner.tactician(brief, tools)

    async def chief(self, brief: dict[str, Any], tools: ToolBox) -> ChiefDecision:
        fault = self._fault()
        if fault == "error":
            raise self._rng.choice(ERRORS)
        if fault == "garbage":
            return ChiefDecision(chosen_option="everywhere", playbook_citations=["POL-PB-999"], justification="Nothing in the playbook says so.")
        return await self._inner.chief(brief, tools)


def pass_hat_k(passes: int, trials_run: int, k: int) -> float:
    """Chance that k trials, drawn without replacement from the ones run, all passed (the unbiased pass^k estimator)."""
    if k > trials_run:
        raise ValueError(f"k ({k}) cannot exceed the number of trials ({trials_run})")
    return math.comb(passes, k) / math.comb(trials_run, k)


async def trials(
    scenario_id: str, n: int, rate: float = 0.0, seed: int = 0, kinds: tuple[str, ...] = ("error", "garbage"),
    models: ModelsConfig | None = None, llm: bool = False, pause_s: float = 0.0,
) -> list[dict[str, Any]]:
    """Run a scenario n times. One row per trial. With `llm`, the model in `models` is the team; otherwise a `FaultyCrew`.

    A real model answers in seconds, and the mock's pursuit lasts 15 s of scenario time: played at once (speed 0) the
    incident would close before the model could answer, so model trials play at real speed.
    """
    speed, timeout = (1.0, 120.0) if llm else (0, 20)
    scripted = await measure_scenario(load_scenario(scenario_id))
    rows = []
    for i in range(n):
        if i and pause_s:
            await asyncio.sleep(pause_s)  # a free plan allows so many tokens a minute: space the trials so the limit is not what is measured
        crew = None if llm else FaultyCrew(rate, seed + i, kinds)
        run = await measure_scenario(load_scenario(scenario_id), models=models, llm_crew=crew, speed=speed, timeout_s=timeout)
        counts = run["event_counts"]
        rows.append({
            "trial": i, "passed": run["passed"], "same_decisions": run["decisions"] == scripted["decisions"],
            "decisions": len(run["decisions"]), "fallbacks": counts.get("brain.agent.fallback", 0),
            "rejected": counts.get("brain.plan.rejected", 0), "fewer_decisions": len(run["decisions"]) < len(scripted["decisions"]),
            "first_action_ms": run["first_action_ms"], "last_action_ms": run["last_action_ms"],
            # What the team decided, so trials can be compared with each other and not only with the scripted team.
            "plan_placed": any(d["params"].get("mode") == "contain" or d["action"] == "broadcast_alert" for d in run["decisions"]),
            "signature": hashlib.sha256(json.dumps(run["decisions"], sort_keys=True).encode()).hexdigest()[:10],
        })
    return rows


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    n, passes = len(rows), sum(1 for r in rows if r["passed"])
    return {
        "trials": n, "passed": passes, "same_decisions": sum(1 for r in rows if r["same_decisions"]),
        "fallbacks": sum(r["fallbacks"] for r in rows), "rejected": sum(r["rejected"] for r in rows),
        "pass_hat_k": {k: round(pass_hat_k(passes, n, k), 3) for k in range(1, n + 1)},
        "plans_placed": sum(1 for r in rows if r.get("plan_placed")),
        # Of the trials that placed a plan, how many placed the commonest one: the team's consistency with itself.
        "plan_agreement": _agreement([r["signature"] for r in rows if r.get("plan_placed")]),
    }


def _agreement(signatures: list[str]) -> float | None:
    if not signatures:
        return None
    return round(max(signatures.count(s) for s in set(signatures)) / len(signatures), 3)
