"""The workspace: a few slots of attention, held by the incidents that matter most right now.

An incident that holds a slot is "lit": it may ask the agent team to deliberate, and its state is
broadcast on the timeline for every other region (and the screen) to see. An incident without a slot
still gets its reflex response; it only waits for a model. A newcomer takes a free slot when it is
salient enough, or displaces the weakest lit incident when it beats it by a margin (hysteresis, so
two near-equal incidents do not trade places on every reading).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from datetime import datetime

from brain.citygraph import MemoryGraphStore
from brain.config import WorkspacePolicy
from brain.contracts import Incident, utcnow
from brain.mind.bids import PackBid
from brain.mind.bus import IncidentClosed, IncidentTouched
from brain.mind.salience import salience
from brain.timeline import Timeline


class Workspace:
    def __init__(
        self, policy: WorkspacePolicy, store: MemoryGraphStore, incidents: dict[str, Incident], timeline: Timeline,
        surprise_of: Callable[[Incident], float] | None = None,
        bidder: Callable[[Incident], list[PackBid]] | None = None,
        urgency_of: Callable[[Incident], float] | None = None,
    ) -> None:
        self.bidder = bidder
        self.surprise_of = surprise_of or (lambda incident: 0.0)
        self.urgency_of = urgency_of or (lambda incident: 0.0)
        self.policy = policy
        self.store = store
        self.incidents = incidents
        self.timeline = timeline
        self.lit: dict[str, float] = {}  # incidents holding a slot, with their salience
        self.slotless: dict[str, float] = {}  # lit but outside the slots: types no team can act on (`slots_for: team`)
        self.counts: Counter[str] = Counter()
        self._deferred: set[str] = set()
        self._deferred_since: dict[str, datetime] = {}

    def is_lit(self, incident_id: str) -> bool:
        return incident_id in self.lit or incident_id in self.slotless

    def _score(self, incident: Incident, now: datetime) -> tuple[float, dict[str, float]]:
        return salience(incident, self.store, list(self.incidents.values()), now, self.policy, self.surprise_of(incident), self.urgency_of(incident))

    def _release(self, incident_id: str, reason: str, trace_id: str | None, score: float | None = None) -> None:
        last = self.lit.pop(incident_id) if incident_id in self.lit else self.slotless.pop(incident_id)
        self.counts["released"] += 1
        self.timeline.emit("brain.workspace.released", incident_id, {
            "reason": reason, "salience": last if score is None else score, "slots": sorted(self.lit),
        }, trace_id)

    async def on_closed(self, message: IncidentClosed) -> None:
        self._deferred.discard(message.incident_id)
        self._deferred_since.pop(message.incident_id, None)
        if message.incident_id in self.lit or message.incident_id in self.slotless:
            self._release(message.incident_id, "closed", message.trace_id)

    async def on_touched(self, message: IncidentTouched) -> None:
        now = message.at or utcnow()
        # Attention fades: a lit incident nobody has added evidence to is rescored with the rest.
        for incident_id in [*self.lit, *self.slotless]:
            incident = self.incidents.get(incident_id)
            score = self._score(incident, now)[0] if incident is not None and incident.status == "open" else 0.0
            if score < self.policy.release_below:
                self._release(incident_id, "faded", message.trace_id, score)
            else:
                (self.lit if incident_id in self.lit else self.slotless)[incident_id] = score

        for incident_id in message.incident_ids:
            incident = self.incidents.get(incident_id)
            if incident is None or incident.status != "open" or self.is_lit(incident_id):
                continue
            score, features = self._score(incident, now)
            self.counts["considered"] += 1
            if score < self.policy.ignite_at:
                self._deferred.discard(incident_id)
                continue
            if self.policy.slots_for == "team" and incident.type not in self.policy.team_types:
                # The team cannot act on this type, so it has no business in a slot: it is lit and broadcast, no more.
                self._deferred.discard(incident_id)
                self.slotless[incident_id] = score
                self.counts["ignited"] += 1
                self.timeline.emit("brain.workspace.ignited", incident_id, {
                    "type": incident.type, "zone_id": incident.zone_id, "salience": score, "features": features,
                    "slots": sorted(self.lit), "slot": False,
                }, message.trace_id)
                self._broadcast_bids(incident, message.trace_id)
                continue
            if len(self.lit) >= self.policy.slots:
                weakest = min(self.lit, key=self.lit.get, default=None)
                # Waiting counts for something, up to a cap: an incident that has been refused for a while is not ranked
                # as if it had just arrived. Time is the readings' own, so a replay ages the same as a live run.
                since = self._deferred_since.setdefault(incident_id, now) if incident_id in self._deferred else None
                aged = min(self.policy.aging_per_s * max((now - since).total_seconds(), 0.0), self.policy.aging_cap) if since else 0.0
                if weakest is None or score + aged <= self.lit[weakest] + self.policy.margin:
                    if incident_id not in self._deferred:
                        self._deferred_since.setdefault(incident_id, now)
                        self._deferred.add(incident_id)
                        self.counts["deferred"] += 1
                        self.timeline.emit("brain.workspace.deferred", incident_id, {
                            "salience": score, "holding": sorted(self.lit),
                        }, message.trace_id)
                    continue
                self._release(weakest, "out-competed", message.trace_id)
            self._deferred.discard(incident_id)
            self._deferred_since.pop(incident_id, None)
            self.lit[incident_id] = score
            self.counts["ignited"] += 1
            self.timeline.emit("brain.workspace.ignited", incident_id, {
                "type": incident.type, "zone_id": incident.zone_id, "salience": score, "features": features,
                "slots": sorted(self.lit), "slot": True,
            }, message.trace_id)
            self._broadcast_bids(incident, message.trace_id)

    def _broadcast_bids(self, incident: Incident, trace_id: str | None) -> None:
        """Ask every pack how well it can answer, say who is recruited, and say so when nobody can."""
        if self.bidder is None:
            return
        bids = self.bidder(incident)
        recruited = [b.pack for b in bids if b.score >= self.policy.recruit_at]
        self.timeline.emit("brain.pack.bid", incident.incident_id, {
            "bids": [{"pack": b.pack, "score": b.score, "reason": b.reason} for b in bids], "recruited": recruited,
        }, trace_id)
        if not recruited:
            self.timeline.emit("brain.pack.uncovered", incident.incident_id, {
                "reasons": {b.pack: b.reason for b in bids},
            }, trace_id)
