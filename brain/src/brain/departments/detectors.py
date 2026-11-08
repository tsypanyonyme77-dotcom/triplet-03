"""Detectors: what reading means an incident, written as data in a pack file.

A detector names a reading type, the incident type it opens and the conditions that must all hold on
the reading's value; it may also say when the incident ends. A missing field never matches (and never
raises), so a Twin that stops sending a field makes a detector quiet, not the Brain wrong.
"""

from __future__ import annotations

import operator
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

_COMPARE = {">=": operator.ge, "<=": operator.le, ">": operator.gt, "<": operator.lt}


class Condition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    op: Literal[">=", "<=", ">", "<", "==", "!=", "in"]
    value: Any
    of: str | None = None  # compare field / of instead of the field itself, e.g. load against capacity


class Detector(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reading: str  # the sensor type this detector reads
    incident: str  # the incident type it opens
    when: list[Condition] = Field(min_length=1)  # an empty list would match every reading
    clear: list[Condition] = Field(default_factory=list)  # when all hold, an open incident of this type ends
    priority: int = 0  # higher wins when several detectors match one reading


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


def _holds_one(condition: Condition, data: dict[str, Any]) -> bool:
    actual = data.get(condition.field)
    if condition.of is not None:
        top, bottom = _number(actual), _number(data.get(condition.of))
        if top is None or not bottom:
            return False
        actual = top / bottom
    if condition.op == "!=":
        return actual != condition.value
    if actual is None:
        return False
    if condition.op == "==":
        return actual == condition.value
    if condition.op == "in":
        return actual in condition.value
    low, high = _number(actual), _number(condition.value)
    return low is not None and high is not None and _COMPARE[condition.op](low, high)


def holds(conditions: list[Condition], data: dict[str, Any]) -> bool:
    return all(_holds_one(condition, data) for condition in conditions)


def first_match(
    detectors: list[tuple[str, Detector]], reading_type: str, data: dict[str, Any]
) -> tuple[str, Detector] | None:
    """The first (pack code, detector) whose reading type and conditions match. `detectors` is in priority order."""
    return next(((code, d) for code, d in detectors if d.reading == reading_type and holds(d.when, data)), None)
