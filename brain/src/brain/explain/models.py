"""What an explanation is made of. Every field is a fact read from the timeline log or the policy; nothing is written by a model."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Step(BaseModel):
    """One thing that happened on the way to the decision, with the region of the Brain it belongs to (the canopy's region ids)."""

    n: int
    layer: Literal["twin", "guardian", "brain"]
    region: str
    event_type: str
    event_id: str
    at_ms: int  # since the first event of the log
    fact: str
    ids: list[str] = Field(default_factory=list)  # readings, verdicts, decisions and incidents this step names


class GateCheck(BaseModel):
    check: str
    passed: bool
    reason: str


class Cited(BaseModel):
    id: str
    kind: Literal["rule", "playbook", "capability", "reference", "other"]
    title: str | None = None
    why: list[str] = Field(default_factory=list)  # how it came to be cited: "cited by the decision", "vector", "keyword", "graph:..."
    resolved: bool | None = None  # None: not checked (no knowledge base was given)


class Margin(BaseModel):
    name: str
    observed: float
    threshold: float
    unit: str
    how_close: str


class Alternative(BaseModel):
    name: str
    chosen: bool
    rationale: str


class Counterfactual(BaseModel):
    change: str  # the one thing that would have to be different
    would_flip: bool  # whether that change would have turned this outcome round
    basis: str  # the rule that says so


class Explanation(BaseModel):
    subject: Literal["decision", "held", "incident"]
    id: str
    outcome: Literal["acted", "held", "open", "closed"]
    headline: str
    steps: list[Step]
    checks: list[GateCheck] = Field(default_factory=list)
    knowledge: list[Cited] = Field(default_factory=list)
    margins: list[Margin] = Field(default_factory=list)
    alternatives: list[Alternative] = Field(default_factory=list)
    counterfactuals: list[Counterfactual] = Field(default_factory=list)
    unresolved: list[str] = Field(default_factory=list)  # ids the explanation names that the log cannot account for
    config_hash: str = ""
    log_chain_head: str = ""  # the hash of the last event of the log it was built from ("" for a live log)
