"""The tunable surface: the only parameters the Brain may change about itself.

Self-improvement here is bounded tuning. The Academy may move a number on this list, inside the range written
here and one step at a time, and nothing else: not the gate, the unit reserve, the action budget, how suspects are
scored, how incidents open, what may be learned, the contracts, perception, or any code. `apply_overlay` is the one
place a tuned value reaches the policy, and it refuses anything off the list or outside its range, so a mistake or
a poisoned file cannot reach further than the surface does.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from brain.config import Policy

# Whole sections of the policy that are never on the surface: safety, resources, identity, and learning itself.
EXCLUDED_SECTIONS = ("gate", "tactics", "scoring", "triage", "learning")


class SurfaceError(ValueError):
    """A value was proposed that is not on the surface, or is outside its range."""


@dataclass(frozen=True)
class Tunable:
    path: str
    low: float
    high: float
    step: float
    owner: str  # the region the number belongs to, for the report

    def check(self, value: Any) -> float:
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise SurfaceError(f"{self.path} must be a number, not {value!r}")
        if not self.low - 1e-9 <= value <= self.high + 1e-9:
            raise SurfaceError(f"{self.path}={value} is outside its range {self.low} to {self.high}")
        return float(value)


def _surface(*rows: tuple[str, float, float, float, str]) -> dict[str, Tunable]:
    return {path: Tunable(path, low, high, step, owner) for path, low, high, step, owner in rows}


SURFACE: dict[str, Tunable] = _surface(
    ("forward.z_threshold", 3.5, 5.5, 0.25, "forward models"),
    ("forward.alpha", 0.05, 0.3, 0.05, "forward models"),
    ("workspace.ignite_at", 0.4, 0.65, 0.025, "workspace"),
    ("workspace.margin", 0.05, 0.2, 0.025, "workspace"),
    ("workspace.release_below", 0.2, 0.4, 0.025, "workspace"),
    ("workspace.freshness_halflife_s", 60, 300, 30, "salience"),
    ("workspace.surprise_boost", 0.0, 0.4, 0.05, "salience"),
    ("workspace.aging_per_s", 0.0, 0.05, 0.005, "workspace"),
    ("workspace.weights.severity", 0.5, 4.0, 0.25, "salience"),
    ("workspace.weights.trust", 0.5, 4.0, 0.25, "salience"),
    ("workspace.weights.corroboration", 0.5, 4.0, 0.25, "salience"),
    ("workspace.weights.novelty", 0.5, 4.0, 0.25, "salience"),
    ("workspace.weights.clustering", 0.5, 4.0, 0.25, "salience"),
)


def _set(tree: dict[str, Any], path: str, value: float) -> None:
    *parents, leaf = path.split(".")
    node = tree
    for part in parents:
        node = node[part]
    node[leaf] = value


def apply_overlay(policy: Policy, overlay: dict[str, float]) -> Policy:
    """The policy with each tuned value laid over it. Refuses a path off the surface or a value outside its range."""
    if not overlay:
        return policy
    tree = policy.model_dump()
    for path, value in overlay.items():
        tunable = SURFACE.get(path)
        if tunable is None:
            raise SurfaceError(f"{path} is not on the tunable surface")
        _set(tree, path, tunable.check(value))
    return Policy.model_validate(tree)


def load_overlay(folder: str | Path | None) -> tuple[dict[str, float], str | None]:
    """The overlay in `folder` and, if it could not be used, why. An unusable overlay is ignored whole: an untuned Brain
    is the safe default, and half an overlay is not one."""
    if not folder:
        return {}, None
    path = Path(folder) / "overlay.yaml"
    if not path.is_file():
        return {}, None
    try:
        data = yaml.safe_load(path.read_text()) or {}
        overlay = data.get("overlay", {})
        if not isinstance(overlay, dict):
            return {}, f"{path} has an `overlay` that is not a mapping"
        for key, value in overlay.items():
            if key not in SURFACE:
                return {}, f"{path} names {key}, which is not on the tunable surface"
            SURFACE[key].check(value)
        return {key: float(value) for key, value in overlay.items()}, None
    except (OSError, yaml.YAMLError, SurfaceError, AttributeError) as error:
        return {}, f"{path} could not be read: {error}"


def save_overlay(folder: str | Path, overlay: dict[str, float], note: str = "") -> None:
    for key, value in overlay.items():
        if key not in SURFACE:
            raise SurfaceError(f"{key} is not on the tunable surface")
        SURFACE[key].check(value)
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "overlay.yaml").write_text(
        "# Written by `brain academy`. Each value was tested on stories it was not tuned on and can be undone with\n"
        "# `brain academy --rollback`. Nothing here is outside the tunable surface (src/brain/mind/surface.py).\n"
        + yaml.safe_dump({"note": note, "overlay": dict(sorted(overlay.items()))}, sort_keys=False))
