"""Temporal specifications: what the Brain promises across time, checked on its own timeline, with no model.

The gate checks each action when it is proposed. These check the *sequence* of what happened: that every action
rested on a verdict that was trusted and not later taken back, that nothing was sent for a closed incident, that a
suspect was not chased twice at once, and that every unit sent came home. Each is a short deterministic function of the
event list alone (never of the store or the gate, so it cannot agree with a bug by sharing it) and each says in one
line what it promises. `verify_log` runs them over a run's events or a saved log.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

from brain.contracts import TimelineEvent

STAND_DOWN = {"recall_unit"}


@dataclass(frozen=True)
class Violation:
    spec: str
    index: int
    message: str


@dataclass(frozen=True)
class Spec:
    id: str
    description: str
    check: Callable[[list[TimelineEvent]], list[Violation]]
    needs_complete_run: bool = False


def _requests(events: list[TimelineEvent]):
    return [(i, e) for i, e in enumerate(events) if e.type == "brain.action.requested"]


def _trust_before_action(events: list[TimelineEvent]) -> list[Violation]:
    trusted: set[str] = set()
    found = []
    for i, e in enumerate(events):
        if e.type == "brain.verdict.received" and e.data.get("status") == "trusted":
            trusted.add(e.data["verdict_id"])
        elif e.type == "brain.action.requested" and e.data.get("trust_ref") not in trusted:
            found.append(Violation("TS-01", i, f"{e.data.get('action')} cites {e.data.get('trust_ref')!r}, which no earlier trusted verdict gave"))
    return found


def _decision_before_request(events: list[TimelineEvent]) -> list[Violation]:
    decided: set[str] = set()
    found = []
    for i, e in enumerate(events):
        if e.type == "brain.decision.made":
            decided.add(e.data["decision_id"])
        elif e.type == "brain.action.requested" and e.data.get("decision_id") not in decided:
            found.append(Violation("TS-02", i, f"request {e.data.get('decision_id')!r} has no earlier decision"))
    return found


def _every_request_answered(events: list[TimelineEvent]) -> list[Violation]:
    answered = {e.data.get("decision_id") for e in events if e.type == "brain.action.result"}
    return [Violation("TS-03", i, f"request {e.data.get('decision_id')!r} ({e.data.get('action')}) was never answered")
            for i, e in _requests(events) if e.data.get("decision_id") not in answered]


def _nothing_after_close(events: list[TimelineEvent]) -> list[Violation]:
    closed: set[str] = set()
    found = []
    for i, e in enumerate(events):
        if e.type == "brain.incident.closed":
            closed.add(e.subject)
        elif e.type == "brain.action.requested" and e.subject in closed and e.data.get("action") not in STAND_DOWN:
            found.append(Violation("TS-04", i, f"{e.data.get('action')} was requested for {e.subject}, which was already closed"))
    return found


def _retraction_bites(events: list[TimelineEvent]) -> list[Violation]:
    verdict_of: dict[str, str] = {}
    retracted: set[str] = set()
    found = []
    for i, e in enumerate(events):
        if e.type == "brain.verdict.received":
            verdict_of[e.subject] = e.data["verdict_id"]
        elif e.type == "brain.evidence.retracted" and e.subject in verdict_of:
            retracted.add(verdict_of[e.subject])
        elif e.type == "brain.action.requested" and e.data.get("trust_ref") in retracted:
            found.append(Violation("TS-05", i, f"{e.data.get('action')} cites {e.data['trust_ref']}, which the Guardian had taken back"))
    return found


class _Units:
    """The units the log says are out, built event by event."""

    def __init__(self) -> None:
        self.pending: dict[str, dict] = {}
        self.out: dict[str, tuple[str | None, str | None, str | None]] = {}  # unit_id -> (incident, mode, target)

    def apply(self, e: TimelineEvent) -> None:
        if e.type == "brain.action.requested":
            self.pending[e.data["decision_id"]] = e.data
        elif e.type == "brain.action.result":
            request = self.pending.pop(e.data.get("decision_id"), None)
            if request is None:
                return
            params = request.get("params", {})
            if request.get("action") == "dispatch_unit" and e.data.get("status") in ("dispatched", "duplicate") and e.data.get("unit_id"):
                self.out[e.data["unit_id"]] = (params.get("incident_id"), params.get("mode"), params.get("target_id"))
            elif request.get("action") == "recall_unit" and e.data.get("status") in ("recalled", "duplicate"):
                self.out.pop(params.get("unit_id"), None)
        elif e.type == "brain.units.released":
            for unit in e.data.get("units", []):
                self.out.pop(unit.get("unit_id"), None)


def _one_chase_per_target(events: list[TimelineEvent]) -> list[Violation]:
    units, found = _Units(), []
    for i, e in enumerate(events):
        if e.type == "brain.action.requested" and e.data.get("action") == "dispatch_unit" and e.data.get("params", {}).get("mode") == "pursuit":
            target = e.data["params"].get("target_id")
            if target and any(mode == "pursuit" and tgt == target for _, mode, tgt in units.out.values()):
                found.append(Violation("TS-06", i, f"a second pursuit of {target} was requested while the first unit was still out"))
        units.apply(e)
    return found


def _every_unit_comes_home(events: list[TimelineEvent]) -> list[Violation]:
    units = _Units()
    for e in events:
        units.apply(e)
    return [Violation("TS-07", len(events) - 1, f"unit {unit_id} ({mode}, {incident}) never came home")
            for unit_id, (incident, mode, _) in sorted(units.out.items())]


SPECS: dict[str, Spec] = {s.id: s for s in (
    Spec("TS-01", "Every action rests on a verdict, given earlier, that was trusted.", _trust_before_action),
    Spec("TS-02", "Every action request follows the decision that made it.", _decision_before_request),
    Spec("TS-03", "Every action request is answered by a result.", _every_request_answered),
    Spec("TS-04", "Once an incident is closed, nothing more is sent for it except a recall.", _nothing_after_close),
    Spec("TS-05", "No action cites a verdict the Guardian has taken back.", _retraction_bites),
    Spec("TS-06", "A suspect is not chased twice at once.", _one_chase_per_target),
    Spec("TS-07", "Every unit sent comes home by the end of a finished run.", _every_unit_comes_home, needs_complete_run=True),
)}


def verify_log(events: Iterable[TimelineEvent], only: Iterable[str] | None = None, complete: bool = True) -> list[Violation]:
    """Every violation of the chosen specifications (default: all) in these events, in order of the event."""
    events = list(events)
    chosen = set(only) if only is not None else set(SPECS)
    found: list[Violation] = []
    for spec in SPECS.values():
        if spec.id in chosen and (complete or not spec.needs_complete_run):
            found.extend(spec.check(events))
    return sorted(found, key=lambda v: (v.index, v.spec))


def read_log(path: Path | str) -> list[TimelineEvent]:
    return [TimelineEvent.model_validate(json.loads(line)) for line in Path(path).read_text().splitlines() if line.strip()]
