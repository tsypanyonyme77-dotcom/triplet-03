"""L5 corroboration: do independent, currently self-consistent sensors in this or adjacent zones agree?

Runs only for notable readings, readings L4 flagged, or every reading in a zone under tightened thresholds."""

from __future__ import annotations

import operator
from collections.abc import Callable
from datetime import datetime
from typing import Any

from guardian.config import Condition, Crosschecks, Thresholds
from guardian.detectors.base import L5, fail, ok
from guardian.ingest.state_store import SensorState, StateStore
from guardian.models import LayerResult, Reading, Status

CMP: dict[str, Callable[[Any, Any], bool]] = {
    ">": operator.gt, ">=": operator.ge, "<": operator.lt, "<=": operator.le, "==": operator.eq, "!=": operator.ne,
}


def condition_holds(c: Condition, value: dict[str, Any], prev: dict[str, Any] | None) -> bool:
    x = value.get(c.field)
    if x is None:
        return False
    if c.op == "in":
        return x in c.value
    if c.op == "dev":
        return isinstance(x, int | float) and abs(x - (c.center or 0)) > c.value
    if c.op == "jump_pct":
        p = (prev or {}).get(c.field)
        return isinstance(p, int | float) and p > 0 and abs(x - p) / p * 100 > c.value
    return CMP[c.op](x, c.value)


class CrosscheckDetector:
    layer = L5

    def __init__(self, state: StateStore, t: Thresholds, cc: Crosschecks,
                 is_contained: Callable[[str], bool]) -> None:
        self.state, self.t, self.cc, self.is_contained = state, t, cc, is_contained

    def in_event(self, sensor_type: str, value: dict[str, Any], prev: dict[str, Any] | None) -> bool:
        return any(condition_holds(c, value, prev) for c in self.t.events.get(sensor_type, []))

    def is_notable(self, r: Reading) -> bool:
        s = self.state.get(r.sensor_id)
        prev = s.history[-1].value if s and s.history else None
        return self.in_event(r.sensor_type, r.value, prev)

    def rule_key(self, r: Reading) -> str:
        if r.sensor_type == "emergency_call":
            return f"emergency_call:{r.value.get('incident_type')}"
        return r.sensor_type

    def _source_ok(self, s: SensorState, ts: datetime) -> bool:
        v = s.latest_verdict
        if s.stale or v is None or s.latest_reading is None or self.is_contained(s.sensor_id):
            return False
        if abs((ts - s.latest_reading.ts).total_seconds()) > self.cc.corroboration_window_s:
            return False
        # trusted, or self-consistent and merely awaiting corroboration itself (avoids event deadlock)
        return v.status == Status.trusted or (v.self_consistent and v.status != Status.untrusted)

    def check(self, r: Reading, claim_event: bool) -> tuple[list[LayerResult], int]:
        """Returns results and the number of distinct agreeing sources."""
        zones = {r.zone_id, *self.cc.adjacency.get(r.zone_id, [])}
        rules = self.cc.rules.get(self.rule_key(r), [])
        votes: list[tuple[str, str, bool]] = []  # (key, voter, agrees)
        for src in rules:
            if src.sensor_type == "emergency_call":
                if r.sensor_type != "emergency_call":
                    continue
                kind, caller = r.value.get("incident_type"), r.value.get("caller_id")
                for z in zones:
                    for ts, call_id, other, other_kind in self.state.zone_calls.get(z, []):
                        if (other != caller and other_kind == kind and call_id != r.value.get("call_id")
                                and abs((r.ts - ts).total_seconds()) <= self.cc.corroboration_window_s):
                            votes.append((src.key, f"caller:{other}", True))
                continue
            for s in self.state.in_zones(zones, src.sensor_type):
                if s.sensor_id == r.sensor_id or not self._source_ok(s, r.ts):
                    continue
                assert s.latest_reading is not None
                prev = s.history[-2].value if len(s.history) >= 2 else None
                event = self.in_event(s.sensor_type, s.latest_reading.value, prev)
                if src.presence_only and not event:
                    continue
                votes.append((src.key, s.sensor_id, event == claim_event))
        # one voice per independent voter (a sensor may serve several keys): majority of its own votes
        voters: dict[str, list[bool]] = {}
        for _, who, agrees in votes:
            voters.setdefault(who, []).append(agrees)
        agree_n = sum(1 for v in voters.values() if sum(v) * 2 > len(v))
        disagree_n = len(voters) - agree_n
        summary = f"{agree_n} agree / {disagree_n} disagree of {len(voters)} independent sources"
        if len(voters) < self.cc.min_sources:
            return [fail(L5, "low", "insufficient_corroboration",
                         f"{summary}; need {self.cc.min_sources} trusted independent sources")], agree_n
        if agree_n > disagree_n:
            return [ok(L5, summary, reason="corroborated")], agree_n
        if agree_n == disagree_n:
            return [fail(L5, "low", "corroboration_inconclusive", summary)], agree_n
        bad_keys = list(dict.fromkeys(k for k, _, a in votes if not a))
        return [fail(L5, "strong", f"no_{k}_corroboration", summary) for k in bad_keys], agree_n
