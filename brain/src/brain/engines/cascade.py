"""What goes dark when a zone loses power, and which single loss would hurt most.

A facility is dark when its zone is cut, or when something it depends on is dark. The dependencies are data (`departments/dependencies.yaml`):
each key depends on the facilities or zones listed under it, and a facility always depends on the grid of its own zone. Weights say how much a
dark facility matters (a hospital far more than a signal). The dependency list is an assumption until the Twin team confirms it.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

WEIGHTS = {"hospital": 10.0, "fire_station": 8.0, "police_station": 8.0, "valve": 3.0, "signal_controller": 2.0}
DEFAULT_WEIGHT = 1.0
DEPENDENCIES = Path(__file__).resolve().parents[1] / "departments" / "dependencies.yaml"


@dataclass
class Impact:
    dark: list[str]
    weight: float
    by_kind: dict[str, int] = field(default_factory=dict)


def load_dependencies(store: Any, path: Path = DEPENDENCIES) -> dict[str, list[str]]:
    """`depends_on: {facility-or-zone: [what it needs]}`. A key or value the topology does not know is rejected, like a pack file."""
    if not path.exists():
        return {}
    raw = (yaml.safe_load(path.read_text()) or {}).get("depends_on", {}) or {}
    known = {f["id"] for f in store.facilities()} | set(store.zones.nodes)
    unknown = sorted(set(raw) | {v for vs in raw.values() for v in vs})
    bad = [name for name in unknown if name not in known]
    if bad:
        raise ValueError(f"dependencies.yaml names {bad}, which the topology does not have")
    return {k: list(v) for k, v in raw.items()}


def load_feeders(store: Any, path: Path = DEPENDENCIES) -> dict[str, dict[str, Any]]:
    """`feeders: {name: {capacity_kw, zones}}`: zones that share one supply. A zone the topology does not have is rejected."""
    if not path.exists():
        return {}
    raw = (yaml.safe_load(path.read_text()) or {}).get("feeders", {}) or {}
    bad = sorted({z for f in raw.values() for z in f.get("zones", [])} - set(store.zones.nodes))
    if bad:
        raise ValueError(f"dependencies.yaml feeders name {bad}, which the topology does not have")
    return {name: {"capacity_kw": float(f["capacity_kw"]), "zones": list(f["zones"])} for name, f in raw.items()}


def cascade(store: Any, deps: dict[str, list[str]], cut_zones: set[str] | list[str]) -> Impact:
    """Breadth-first: every facility in a cut zone is dark, then everything that depends on something dark."""
    facilities = {f["id"]: f for f in store.facilities()}
    dark: set[str] = set()
    lost_zones = set(cut_zones)
    queue = deque(sorted(fid for fid, f in facilities.items() if f["zone_id"] in lost_zones))
    dark.update(queue)
    needs = {fid: set(deps.get(fid, [])) | {facilities[fid]["zone_id"]} for fid in facilities}
    while queue:
        lost = queue.popleft()
        for fid in sorted(facilities):
            if fid not in dark and (lost in needs[fid]):
                dark.add(fid)
                queue.append(fid)
    by_kind: dict[str, int] = {}
    for fid in dark:
        by_kind[facilities[fid]["type"]] = by_kind.get(facilities[fid]["type"], 0) + 1
    return Impact(sorted(dark), sum(WEIGHTS.get(facilities[f]["type"], DEFAULT_WEIGHT) for f in dark), dict(sorted(by_kind.items())))


def n_minus_1(store: Any, deps: dict[str, list[str]]) -> list[tuple[str, Impact]]:
    """Every single zone loss, the worst first."""
    ranked = [(zone, cascade(store, deps, {zone})) for zone in sorted(store.zones.nodes)]
    return sorted(ranked, key=lambda item: (-item[1].weight, item[0]))
