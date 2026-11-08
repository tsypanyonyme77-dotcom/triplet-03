"""Variants: a held-out set of scenarios, checked by metamorphic relations.

A Test Book scenario says what the Brain must do. A variant of it (the same story shifted in time, with
different sensor noise, with a calm decoy sensor elsewhere in the city) must be decided exactly as the base
scenario is, so no expectations have to be written by hand and a tuner or calibrator can be scored on
stories it never saw. Seeds below 1000 are for training and tuning; seeds from 1000 are held out and may
only be used to score.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from typing import Any

from brain.baseline import measure_scenario
from brain.config import Policy
from brain.scenario import expand_streams, load_raw_scenario

TRAIN_SEEDS = range(0, 1000)
HELD_OUT_SEEDS = range(1000, 1100)

Transform = Callable[[dict[str, Any], int], dict[str, Any]]


def load_raw(scenario_id: str) -> dict[str, Any]:
    return load_raw_scenario(scenario_id)


def shift_time(scenario: dict[str, Any], seed: int) -> dict[str, Any]:
    """Every timed event and stream starts later by the same amount: the story is the same, the clock is not."""
    delta = (seed % 7) * 250 + 250
    shifted = copy.deepcopy(scenario)
    for event in shifted.get("events", []):
        if "at_ms" in event:
            event["at_ms"] += delta
    for stream in shifted.get("streams", []):
        stream["from_ms"] += delta
        stream["to_ms"] += delta
    return shifted


def reseed(scenario: dict[str, Any], seed: int) -> dict[str, Any]:
    """The same sensors with different noise (the base level and the noise size are unchanged)."""
    changed = copy.deepcopy(scenario)
    for stream in changed.get("streams", []):
        stream["seed"] = stream.get("seed", 0) + seed
    return changed


def decoy(scenario: dict[str, Any], seed: int) -> dict[str, Any]:
    """A calm traffic camera in a zone where nothing happens, for the length of the scenario."""
    changed = copy.deepcopy(scenario)
    topology = changed.get("topology") or {}
    used = {e["zone_id"] for e in changed.get("events", []) if "zone_id" in e} | {s["zone_id"] for s in changed.get("streams", [])}
    free = [zone["id"] for zone in topology.get("zones", []) if zone["id"] not in used]
    if not free:
        return changed
    end = max([e["at_ms"] for e in changed.get("events", []) if "at_ms" in e] + [s["to_ms"] for s in changed.get("streams", [])] + [0]) + 1000
    changed.setdefault("streams", []).append({
        "sensor_id": f"decoy-{seed}", "type": "traffic_camera", "zone_id": free[seed % len(free)],
        "from_ms": 0, "to_ms": end, "every_ms": 1000,
        "base": {"congestion_score": 0.2, "vehicle_count": 20, "avg_speed_kmh": 50.0, "smoke_detected": False},
        "noise": {"congestion_score": 0.02, "vehicle_count": 2, "avg_speed_kmh": 2.0},
        "clamp": {"congestion_score": [0.1, 0.3], "vehicle_count": [14, 26], "avg_speed_kmh": [44.0, 56.0]},
        "seed": seed,
    })
    return changed


TRANSFORMS: dict[str, Transform] = {"shift_time": shift_time, "reseed": reseed, "decoy": decoy}


def variants(scenario: dict[str, Any], seeds, transforms: dict[str, Transform] | None = None) -> list[dict[str, Any]]:
    """One variant per transform and seed, skipping a transform that would change nothing in this scenario."""
    found = []
    for name, transform in (transforms or TRANSFORMS).items():
        for seed in seeds:
            changed = transform(scenario, seed)
            if changed == scenario:
                continue
            found.append({**changed, "variant_of": scenario["id"], "transform": name, "seed": seed})
    return found


def policy_with(settings: list[str]) -> Policy | None:
    """A policy with `section.field=value` settings laid over the defaults (values are JSON: 0.3, true, "cause")."""
    if not settings:
        return None
    overlay: dict[str, Any] = {}
    for item in settings:
        path, _, raw = item.partition("=")
        node = overlay
        *parents, leaf = path.split(".")
        for part in parents:
            node = node.setdefault(part, {})
        try:
            node[leaf] = json.loads(raw)
        except json.JSONDecodeError:
            node[leaf] = raw
    return Policy.model_validate(overlay)


async def check(scenario_ids: list[str], seeds, transforms: dict[str, Transform] | None = None,
                policy: Policy | None = None) -> list[dict[str, Any]]:
    """Run each base scenario once and each of its variants once; one row per variant says whether it was decided the same.

    A transform that is applied to a scenario and changes nothing is not a row, so a scenario without streams has no
    `reseed` rows. In `transforms=` form a deliberately breaking transform can be passed in to prove the check bites.
    """
    rows = []
    for scenario_id in scenario_ids:
        raw = load_raw_scenario(scenario_id)
        base = await measure_scenario(expand_streams(raw), policy)
        for variant in variants(raw, list(seeds), transforms):
            result = await measure_scenario(expand_streams({k: v for k, v in variant.items() if k not in ("variant_of", "transform", "seed")}), policy)
            same_decisions = result["decisions"] == base["decisions"]
            same_blocks = result["blocked"] == base["blocked"]
            rows.append({
                "scenario": scenario_id, "transform": variant["transform"], "seed": variant["seed"],
                "same_decisions": same_decisions, "same_blocks": same_blocks,
                # A decoy adds readings, so a base scenario's own count expectations may not hold: report them, do not judge by them.
                "expectations_met": result["passed"], "passed": same_decisions and same_blocks,
            })
    return rows


def table(rows: list[dict[str, Any]]) -> str:
    """One line per scenario and transform: how many seeds were decided the same."""
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in rows:
        groups.setdefault((row["scenario"], row["transform"]), []).append(row)
    lines = ["| scenario | transform | seeds | decided the same |", "| --- | --- | --- | --- |"]
    for (scenario_id, name), group in groups.items():
        same = sum(1 for r in group if r["same_decisions"] and r["same_blocks"])
        lines.append(f"| {scenario_id} | {name} | {len(group)} | {same} of {len(group)} |")
    return "\n".join(lines)
