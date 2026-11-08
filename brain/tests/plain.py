"""The pipeline as it decided before the solvers were switched on (6 Nov): the older frozen baselines are checked against this."""

from brain.config import Policy

PLAIN = {"optimiser": {"dispatch": "off", "shed": "off", "perimeter": "off"}, "math": {"kalman": "off", "prewarn_s": 0}, "orchestration": {"planner": "off"}}


def plain(**sections: dict) -> Policy:
    """Every solver off, with `sections` laid over the other policy settings."""
    merged = {**sections, **{k: {**sections.get(k, {}), **v} for k, v in PLAIN.items()}}
    return Policy.model_validate(merged)
