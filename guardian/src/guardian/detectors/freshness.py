"""L2 freshness (hard gate): strictly increasing sequence_no per sensor and bounded timestamp skew."""

from __future__ import annotations

from guardian.clock import Clock
from guardian.detectors.base import L2, fail, ok
from guardian.ingest.state_store import StateStore
from guardian.models import LayerResult, Reading


class FreshnessDetector:
    layer = L2

    def __init__(self, state: StateStore, clock: Clock, max_skew_s: float) -> None:
        self.state, self.clock, self.max_skew_s = state, clock, max_skew_s

    def check(self, r: Reading) -> list[LayerResult]:
        s = self.state.get(r.sensor_id)
        if s is not None and s.last_seq is not None:
            if r.sequence_reset:
                # A reset is only honoured when it is newer than anything seen: replaying an old reset fails.
                if s.last_ts is not None and r.ts <= s.last_ts:
                    return [fail(L2, "hard", "replay", f"sequence_reset with old timestamp {r.ts.isoformat()}")]
            elif r.sequence_no <= s.last_seq:
                return [fail(L2, "hard", "replay",
                             f"sequence_no {r.sequence_no} <= last seen {s.last_seq}")]
        skew = abs((r.ts - self.clock.now()).total_seconds())
        if skew > self.max_skew_s:
            return [fail(L2, "hard", "timestamp_skew", f"timestamp skew {skew:.1f}s > {self.max_skew_s}s")]
        if r.sequence_reset:
            return [ok(L2, "sequence reset accepted (agreed Twin restart rule)", reason="sequence_reset")]
        return [ok(L2, "sequence and timestamp fresh")]
