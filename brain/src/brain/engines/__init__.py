"""Decision engines: solvers that return their answer with the proof of how good it is.

An engine proposes; it never acts. Its output goes through the same `ProposedAction` and the same gate as a rule's or an agent's, and
each answer carries a `Certificate`: whether it is optimal or only feasible, the objective, the bound, how long it took and a hash of the
problem it was given, so the answer can be checked and asked again.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, Field


class Certificate(BaseModel):
    engine: str
    status: Literal["optimal", "feasible", "infeasible", "fallback", "timeout"]
    objective: float | None = None
    bound: float | None = None
    gap: float | None = None
    elapsed_ms: float = 0.0  # measured time: the timeline keeps it out of `data`
    inputs_hash: str
    slack: dict[str, float] = Field(default_factory=dict)


def inputs_hash(problem: object) -> str:
    return hashlib.sha256(json.dumps(problem, sort_keys=True, default=str).encode()).hexdigest()[:16]
