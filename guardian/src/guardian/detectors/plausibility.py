"""L3a range and unit: ranges, sign, internal consistency, and a ~100x unit-mix heuristic (cm sent as m)."""

from __future__ import annotations

import operator

from guardian.config import Thresholds
from guardian.detectors.base import L3A, fail, ok
from guardian.models import LayerResult, Reading

OPS = {"<=": operator.le, "<": operator.lt, ">=": operator.ge, ">": operator.gt}


class PlausibilityDetector:
    layer = L3A

    def __init__(self, thresholds: Thresholds) -> None:
        self.t = thresholds

    def check(self, r: Reading) -> list[LayerResult]:
        out: list[LayerResult] = []
        k = self.t.unit_mismatch_factor
        for name, lim in self.t.fields.get(r.sensor_type, {}).items():
            v = r.value.get(name)
            if not isinstance(v, int | float) or isinstance(v, bool):
                continue
            lo = lim.min if lim.min is not None else float("-inf")
            hi = lim.max if lim.max is not None else float("inf")
            if lo <= v <= hi:
                continue
            if v > hi * k / 10 and lo <= v / k <= hi:  # an order of magnitude off, fits after /k
                out.append(fail(L3A, "strong", "unit_mismatch",
                                f"{name}={v} is ~{k:g}x the valid range [{lo:g}, {hi:g}] (unit mix-up?)"))
            else:
                out.append(fail(L3A, "strong", "out_of_range", f"{name}={v} outside [{lo:g}, {hi:g}]"))
        for c in self.t.consistency.get(r.sensor_type, []):
            a, b = r.value.get(c.left), r.value.get(c.right)
            if isinstance(a, int | float) and isinstance(b, int | float) and not OPS[c.op](a, b):
                out.append(fail(L3A, "strong", "inconsistent", f"{c.left}={a} not {c.op} {c.right}={b}"))
        return out or [ok(L3A, "values in range and consistent")]
