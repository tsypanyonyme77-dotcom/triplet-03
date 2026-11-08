"""L6 liveness and rate: stale sensors (no reading in 2x interval), per-zone call floods, duplicate call_ids,
per-sensor message rate. Floods are throttled and marked for corroboration, never dropped."""

from __future__ import annotations

from collections import deque
from datetime import datetime

from guardian.clock import Clock
from guardian.config import SensorRegistry, Thresholds
from guardian.detectors.base import L6, fail, ok
from guardian.ingest.state_store import SensorState, StateStore
from guardian.models import LayerResult, Reading


class LivenessDetector:
    layer = L6

    def __init__(self, state: StateStore, t: Thresholds, registry: SensorRegistry, clock: Clock) -> None:
        self.state, self.t, self.registry, self.clock = state, t, registry, clock

    def check(self, r: Reading) -> list[LayerResult]:
        now = self.clock.now()
        if r.sensor_type == "emergency_call":
            call_id = str(r.value["call_id"])
            if call_id in self.state.call_ids:
                return [fail(L6, "hard", "duplicate_call", f"call_id {call_id} already received")]
            self.state.remember_call(call_id, now)
            calls = self.state.zone_calls.setdefault(r.zone_id, deque(maxlen=10_000))
            calls.append((r.ts, call_id, str(r.value["caller_id"]), str(r.value["incident_type"])))
            window = self.t.call_flood.window_s
            recent = sum(1 for ts, *_ in calls if (r.ts - ts).total_seconds() <= window)
            if recent > self.t.call_flood.max_calls_per_zone:
                return [
                    fail(L6, "medium", "call_flood",
                         f"{recent} calls in {r.zone_id} within {window:.0f}s "
                         f"(> {self.t.call_flood.max_calls_per_zone}); throttled, not dropped"),
                    fail(L6, "low", "needs_corroboration", "call accepted during a flood: corroborate first"),
                ]
            return [ok(L6, f"{recent} calls in window")]
        s = self.state.get(r.sensor_id)
        if s is not None:
            per_s = sum(1 for t in s.arrivals if (now - t).total_seconds() < 1.0)
            if per_s > self.t.rate.max_msgs_per_s:
                return [fail(L6, "medium", "rate_exceeded",
                             f"{per_s} messages in 1s (> {self.t.rate.max_msgs_per_s}/s)")]
        return [ok(L6, "alive, normal rate")]

    def interval(self, s: SensorState) -> float | None:
        spec = self.registry.sensor_types.get(s.sensor_type)
        return spec.expected_interval_s if spec else None

    def is_stale(self, s: SensorState, now: datetime | None = None) -> bool:
        iv = self.interval(s)
        if iv is None:
            return s.stale
        if s.last_seen is None:
            return True  # recovered from disk but not heard from since start: unknown until fresh data
        return ((now or self.clock.now()) - s.last_seen).total_seconds() > 2 * iv

    def tick(self) -> list[SensorState]:
        """Mark sensors stale; returns the ones that just became stale."""
        now = self.clock.now()
        changed = []
        for s in self.state.sensors.values():
            if not s.stale and s.last_seen is not None and self.is_stale(s, now):
                s.stale = True
                changed.append(s)
        return changed
