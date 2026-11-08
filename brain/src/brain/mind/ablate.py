"""Ablations: switch one region of the Brain off, replay the Test Book, and report what it saved and what it changed.

A region earns its place only if switching it off moves a number the report can show. The gate has no switch:
it is not a region, it is the only way out.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from brain.baseline import measure_scenario
from brain.config import BrainConfig, PartnersConfig, Policy
from brain.mind.curve import learning_curve
from brain.scenario import load_scenario

ABLATIONS: dict[str, dict[str, Any]] = {
    "full": {},
    "no workspace": {"workspace": {"enabled": False}},
    "no forward models": {"forward": {"enabled": False}},
    "no bids": {"workspace": {"bids": False}},
    "no learned reflexes": {"learning": {"use_learned": False}},
}
BURST = "d3"


async def ablate(suite: list[str], workdir: Path) -> dict[str, Any]:
    """Run `suite` under each ablation. A learned reflex is taught first (two runs of d3 and one sleep) so that it can be switched off."""
    await learning_curve("d3", runs=2, workdir=workdir, policy=Policy(), suite=["d1", "d3"])
    partners = PartnersConfig(brain=BrainConfig(learned_dir=str(workdir / "learned")))
    runs: dict[str, dict[str, dict[str, Any]]] = {}
    for name, overlay in ABLATIONS.items():
        policy = Policy.model_validate(overlay)
        runs[name] = {sid: await measure_scenario(load_scenario(sid), policy, partners) for sid in suite}

    configs = {}
    for name, measured in runs.items():
        # `passed` is left out on purpose: a scenario's own order checks name the events of the path that was switched off.
        changed = [sid for sid in suite if any(runs["full"][sid][key] != measured[sid][key] for key in ("decisions", "blocked"))]
        count = lambda kind: sum(r["event_counts"].get(kind, 0) for r in measured.values())  # noqa: E731
        configs[name] = {
            "passed": sum(r["passed"] for r in measured.values()),
            "decisions_changed": changed,
            "team_runs": sum(r["deliberations"] for r in measured.values()),
            "burst_team_runs": measured[BURST]["deliberations"] if BURST in measured else None,
            "held_for_surprise": sum(r["blocked"].count("surprise") for r in measured.values()),
            "bids_reported": count("brain.pack.bid"),
            "workspace_events": count("brain.workspace.ignited") + count("brain.workspace.deferred"),
            "learned_plans_used": sum(r["compiled_plans"] for r in measured.values()),
        }
    return {"suite": suite, "configs": configs}


def table(result: dict[str, Any]) -> str:
    rows = ["| configuration | scenarios passing | decisions changed | team runs | team runs in the burst | held for surprise | bids reported | learned plans used |",
            "|---|---|---|---|---|---|---|---|"]
    for name, c in result["configs"].items():
        rows.append(f"| {name} | {c['passed']} of {len(result['suite'])} | {', '.join(c['decisions_changed']) or 'none'} | {c['team_runs']} | "
                    f"{c['burst_team_runs']} | {c['held_for_surprise']} | {c['bids_reported']} | {c['learned_plans_used']} |")
    return "\n".join(rows) + "\n"


def dump(result: dict[str, Any]) -> str:
    return json.dumps(result, indent=2) + "\n"
