"""L4 dynamics: rate of change vs last-known-good, flatline, EWMA z-score, hour-of-day baseline, slow drift."""

from __future__ import annotations

import math
from datetime import timedelta

from guardian.config import CityModel, Thresholds
from guardian.detectors.base import L4, fail, ok
from guardian.detectors.patterns.baseline import BaselineModel
from guardian.ingest.state_store import SensorState, StateStore
from guardian.models import LayerResult, Reading


class DynamicsDetector:
    layer = L4

    def __init__(self, state: StateStore, t: Thresholds, city: CityModel, baseline: BaselineModel,
                 ml: object | None = None) -> None:
        self.state, self.t, self.city, self.baseline, self.ml = state, t, city, baseline, ml

    def _hour(self, r: Reading) -> int:
        return (r.ts + timedelta(hours=self.city.timezone_offset_h)).hour

    def numeric(self, r: Reading) -> dict[str, float]:
        return {f: float(r.value[f]) for f in self.t.fields.get(r.sensor_type, {})
                if isinstance(r.value.get(f), int | float) and not isinstance(r.value.get(f), bool)}

    def check(self, r: Reading) -> list[LayerResult]:
        s = self.state.get(r.sensor_id)
        if s is None:
            return [ok(L4, "no history yet")]
        lims = self.t.fields.get(r.sensor_type, {})
        nums = self.numeric(r)
        out: list[LayerResult] = []
        # rate of change against the last trusted value, so an attacker cannot ratchet from its own lies
        if s.lkg is not None:
            dt = (r.ts - s.lkg.ts).total_seconds()
            for f, x in nums.items():
                lim = lims[f].max_rate_per_s
                prev = s.lkg.value.get(f)
                if lim and dt > 0 and isinstance(prev, int | float):
                    rate = abs(x - prev) / dt
                    if rate > lim:
                        out.append(fail(L4, "medium", "rate_of_change",
                                        f"{f} changed {prev}→{x} in {dt:.0f}s ({rate:.4g}/s > {lim}/s)"))
        out += self._flatline(s, r, nums)
        z = self.t.zscore
        for f, x in nums.items():
            mean, var, n = s.ewma.get(f, (x, 0.0, 0))
            if n >= z.min_history:
                std = max(math.sqrt(var), lims[f].noise_floor, 1e-9)
                score = (x - mean) / std
                if abs(score) > z.limit:
                    out.append(fail(L4, "medium", "zscore_outlier",
                                    f"{f}={x} is {score:+.1f} sigma from EWMA {mean:.4g}"))
            bz = self.baseline.zscore(r.sensor_id, f, self._hour(r), x, lims[f].noise_floor)
            if bz is not None:
                if abs(bz) > self.t.baseline.sigma:
                    out.append(fail(L4, "medium", "baseline_deviation",
                                    f"{f}={x} is {bz:+.1f} sigma from the {self._hour(r):02d}:00 baseline"))
                if self.baseline.observe_deviation(r.sensor_id, f, bz):
                    out.append(fail(L4, "low", "slow_drift",
                                    f"{f} drifting one way from its baseline over "
                                    f"{self.t.baseline.drift_window} readings"))
        if self.ml is not None:
            out += self.ml.check(r, s)  # type: ignore[attr-defined]
        return out or [ok(L4, "dynamics normal")]

    def _flatline(self, s: SensorState, r: Reading, nums: dict[str, float]) -> list[LayerResult]:
        n, d = self.t.flatline_n, self.t.flatline_decimals
        if not nums or len(s.history) < n - 1:
            return []
        lims = self.t.fields[r.sensor_type]
        if all(lims[f].min is not None and x == lims[f].min for f, x in nums.items()):
            return []  # resting at its floor (dry rain gauge, idle flow) is not frozen
        key = {f: round(x, d) for f, x in nums.items()}
        recent = list(s.history)[-(n - 1):]
        if all({f: round(float(e.value.get(f, math.nan)), d) for f in key} == key for e in recent):
            return [fail(L4, "medium", "flatline", f"{n} identical readings {key}")]
        return []

    def learn(self, r: Reading) -> None:
        """Update EWMA and baseline from a trusted reading only (poisoning defence)."""
        s = self.state.get(r.sensor_id)
        if s is None:
            return
        a = self.t.zscore.alpha
        for f, x in self.numeric(r).items():
            mean, var, n = s.ewma.get(f, (x, 0.0, 0))
            d = x - mean
            s.ewma[f] = (mean + a * d, (1 - a) * (var + a * d * d), n + 1)
            self.baseline.update(r.sensor_id, f, self._hour(r), x)

