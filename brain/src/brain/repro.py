"""Reproducibility: run a scenario again and report what changed, level by level.

A fixed input should give the same output. Four things are kept apart, because each has a different cause and a different claim:
the *decisions* (what was sent and what was refused), the *stream* (every event, with ids, times and measured durations
removed), the *bytes* of the log, and the *prompt* the agents saw. `brain repro` runs a scenario N times and says, for each
level, whether the runs were identical or how many different results there were, and where they first differ. Nothing is
assumed: a field that varies is found by comparing runs.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from brain.contracts.signing import canonical_json

VOLATILE = ("id", "time", "timing")  # what an event carries that is allowed to differ between two runs of the same input


def normalise(event: dict[str, Any]) -> dict[str, Any]:
    """An event without its id, its time and its measured durations."""
    return {key: value for key, value in event.items() if key not in VOLATILE}


@dataclass
class VaryingField:
    path: str  # `<event type>.<field path>`, for example brain.options.prepared.data.usage.seconds
    values: list[Any]  # the distinct values seen, in the order they first appeared


@dataclass
class Level:
    name: str
    distinct: int  # how many different results the runs gave
    first_difference: str | None = None

    @property
    def identical(self) -> bool:
        return self.distinct == 1


def _leaves(value: Any, path: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, inner in value.items():
            out.update(_leaves(inner, f"{path}.{key}" if path else str(key)))
        return out
    if isinstance(value, list):
        out = {}
        for index, inner in enumerate(value):
            out.update(_leaves(inner, f"{path}[{index}]"))
        return out
    return {path: value}


def census(runs: list[list[dict[str, Any]]]) -> list[VaryingField]:
    """Every event field whose value differs between the runs, compared event by event in order (ids, times and timing aside)."""
    found: dict[str, list[Any]] = {}
    shortest = min((len(run) for run in runs), default=0)
    for position in range(shortest):
        flat = [_leaves(normalise(run[position])) for run in runs]
        for leaf in dict.fromkeys(path for one in flat for path in one):
            seen = [one.get(leaf) for one in flat]
            if len({json.dumps(value, sort_keys=True, default=str) for value in seen}) > 1:
                label = f"{runs[0][position].get('type', '?')}.{leaf}"
                values = found.setdefault(label, [])
                for value in seen:
                    if value not in values:
                        values.append(value)
    return [VaryingField(path, values) for path, values in found.items()]


def decisions_of(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """What the Brain decided to send, order-free, the way `brain baseline` compares it."""
    rows = [{"action": e["data"]["action"], "actuator_id": e["data"]["actuator_id"], "params": e["data"]["params"]}
            for e in events if e.get("type") == "brain.decision.made"]
    return sorted(rows, key=lambda row: canonical_json(row))


def _signature(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()[:10]


def _first_raw_difference(runs: list[list[dict[str, Any]]]) -> str | None:
    base = runs[0]
    for other in runs[1:]:
        for a, b in zip(base, other):
            for leaf, value in _leaves(a).items():
                if _leaves(b).get(leaf) != value:
                    return f"{a.get('type', '?')}.{leaf}"
    return None


def levels(runs: list[list[dict[str, Any]]], briefs: list[dict[str, Any]] | None = None) -> list[Level]:
    """Decisions, stream, bytes and (when the agents' briefs were captured) prompt, each with its distinct count."""
    out = [Level("decisions", len({_signature(decisions_of(run)) for run in runs}))]
    stream = Level("stream", len({_signature([normalise(e) for e in run]) for run in runs}))
    if stream.distinct > 1:
        counts = sorted({len(run) for run in runs})
        if len(counts) > 1:
            stream.first_difference = f"event count: {counts[0]} against {counts[1]}"
        else:
            varying = census(runs)
            stream.first_difference = varying[0].path if varying else None
    out.append(stream)
    raw = Level("bytes", len({_signature(run) for run in runs}))
    if raw.distinct > 1:
        raw.first_difference = _first_raw_difference(runs)
    out.append(raw)
    if briefs is not None:
        prompt = Level("prompt", len({_signature(brief) for brief in briefs}))
        if prompt.distinct > 1:
            for other in briefs[1:]:
                differing = [leaf for leaf, value in _leaves(briefs[0]).items() if _leaves(other).get(leaf) != value]
                if differing:
                    prompt.first_difference = differing[0]
                    break
        out.append(prompt)
    return out


def format_table(scenario_id: str, runs: int, rows: list[Level]) -> str:
    lines = [f"{scenario_id}: {runs} runs"]
    for row in rows:
        verdict = "identical" if row.identical else f"{row.distinct} different results"
        where = f"  (first difference: {row.first_difference})" if row.first_difference else ""
        lines.append(f"  {row.name:10} {verdict}{where}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- running a scenario


async def run_events(scenario_id: str, deterministic: bool = False, models: Any = None) -> list[dict[str, Any]]:
    """One in-process run of a Test Book scenario with the scripted team; its events as plain dicts."""
    from brain import baseline
    from brain.scenario import DEV_SECRETS, inproc_partners, load_scenario, run_scenario

    for name, value in DEV_SECRETS.items():
        os.environ.setdefault(name, value)
    result = await run_scenario(load_scenario(scenario_id), inproc_partners(), models=models or baseline.MODELS, speed=0, timeout_s=30, deterministic=deterministic)
    return [event.model_dump(mode="json") for event in result.sink.events]


async def run_briefs(scenario_id: str, deterministic: bool = False, models: Any = None) -> dict[str, Any]:
    """The brief each agent role receives in one run. A recording crew answers like the scripted one, so the run is unchanged."""
    from brain import baseline
    from brain.config import Policy
    from brain.departments.team import LLMCrew, ScriptedCrew
    from brain.scenario import DEV_SECRETS, inproc_partners, load_scenario, run_scenario

    for name, value in DEV_SECRETS.items():
        os.environ.setdefault(name, value)
    seen: dict[str, Any] = {}
    scripted = ScriptedCrew(Policy(), "police_station")

    class RecordingCrew(LLMCrew):
        async def _run(self, role, brief, tools):  # type: ignore[no-untyped-def]
            seen.setdefault(role, json.loads(json.dumps(brief, default=str)))
            return await getattr(scripted, role)(brief, tools)

    crew = RecordingCrew({role: "groq:none" for role in ("analyst", "tactician", "chief")}, {}, "auto", model_factory=lambda spec, **options: object())
    await run_scenario(load_scenario(scenario_id), inproc_partners(), models=models or baseline.MODELS, speed=0, timeout_s=30, llm_crew=crew, deterministic=deterministic)
    return seen


async def collect(scenario_id: str, runs: int, processes: bool = False, deterministic: bool = False) -> list[list[dict[str, Any]]]:
    """N runs of a scenario, in this process or each in a fresh process with its own PYTHONHASHSEED."""
    if not processes:
        return [await run_events(scenario_id, deterministic) for _ in range(runs)]
    out = []
    with tempfile.TemporaryDirectory() as folder:
        for index in range(runs):
            target = Path(folder) / f"run-{index}.json"
            await asyncio.to_thread(subprocess.run, [sys.executable, "-m", "brain.repro", "worker", scenario_id, str(target), str(deterministic)], check=True,
                                    env={**os.environ, "PYTHONHASHSEED": str(index)}, stdout=subprocess.DEVNULL)
            out.append(json.loads(target.read_text()))
    return out


async def report(scenario_id: str, runs: int, processes: bool = False, prompts: bool = True, deterministic: bool = False) -> tuple[list[Level], list[list[dict[str, Any]]]]:
    collected = await collect(scenario_id, runs, processes, deterministic)
    briefs = [await run_briefs(scenario_id, deterministic) for _ in range(runs)] if prompts else None
    return levels(collected, briefs), collected


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "worker":
        Path(sys.argv[3]).write_text(json.dumps(asyncio.run(run_events(sys.argv[2], sys.argv[4] == "True"))))
