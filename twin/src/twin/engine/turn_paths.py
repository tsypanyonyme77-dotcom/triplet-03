"""Smooth paths for vehicles through a node (turns, and lane shifts going straight).

The engine moves vehicles along straight edges (`dist_on_edge`), and IDM, lights
and rule checks all work on that. Drawn literally, a vehicle snaps its heading
by the full turn angle at the node and jumps sideways to the new lane. Instead,
within `turn_zone` metres either side of the node, the drawn position follows a
quadratic Bezier curve from the incoming lane to the outgoing lane, with the
corner where the two lane lines meet as control point. Only x, y and heading
change; distances along edges are untouched.

The curve is walked at constant speed along its own length: progress over the
2 x zone metres of straight-line distance maps to the same fraction of the curve
length. A tight right turn is shorter than 2 x zone, so the car is drawn slower
there, as a driver would turn.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

TURN_ZONE_M = 8.0          # about where the intersection square starts (kerb line of the cross street)
ZONE_MAX_EDGE_SHARE = 0.45  # on short edges, keep the zones at both ends from overlapping
SAMPLES = 24               # arc-length table resolution

Point = tuple[float, float]


def turn_zone(len_in: float, len_out: float) -> float:
    return min(TURN_ZONE_M, ZONE_MAX_EDGE_SHARE * len_in, ZONE_MAX_EDGE_SHARE * len_out)


def _corner(p0: Point, d0: Point, p2: Point, d2: Point) -> Point:
    """Where the line through p0 along d0 meets the line through p2 along d2;
    the midpoint if they are (nearly) parallel, e.g. going straight on."""
    cross = d0[0] * d2[1] - d0[1] * d2[0]
    if abs(cross) < 1e-6:
        return (p0[0] + p2[0]) / 2, (p0[1] + p2[1]) / 2
    a = ((p2[0] - p0[0]) * d2[1] - (p2[1] - p0[1]) * d2[0]) / cross
    return p0[0] + d0[0] * a, p0[1] + d0[1] * a


@dataclass(frozen=True)
class TurnCurve:
    p0: Point
    p1: Point
    p2: Point
    ts: tuple[float, ...]       # curve parameter at each sample
    lengths: tuple[float, ...]  # arc length from p0 at each sample
    max_curvature: float        # 1/m, tightest point (the apex), for planning the turning speed

    @classmethod
    def build(cls, p0: Point, d0: Point, p2: Point, d2: Point) -> "TurnCurve":
        p1 = _corner(p0, d0, p2, d2)
        ts = [i / SAMPLES for i in range(SAMPLES + 1)]
        lengths = [0.0]
        prev = p0
        for t in ts[1:]:
            pt = _bezier(p0, p1, p2, t)
            lengths.append(lengths[-1] + math.hypot(pt[0] - prev[0], pt[1] - prev[1]))
            prev = pt
        max_curvature = max(_curvature(p0, p1, p2, t) for t in ts)
        return cls(p0, p1, p2, tuple(ts), tuple(lengths), max_curvature)

    @property
    def length(self) -> float:
        return self.lengths[-1]

    def at(self, fraction: float) -> tuple[float, float, float]:
        """(x, y, heading) at `fraction` (0..1) of the curve's length."""
        target = min(max(fraction, 0.0), 1.0) * self.lengths[-1]
        i = 1
        while i < SAMPLES and self.lengths[i] < target:
            i += 1
        span = self.lengths[i] - self.lengths[i - 1]
        k = 0.0 if span < 1e-9 else (target - self.lengths[i - 1]) / span
        t = self.ts[i - 1] + (self.ts[i] - self.ts[i - 1]) * k
        x, y = _bezier(self.p0, self.p1, self.p2, t)
        tx, ty = _tangent(self.p0, self.p1, self.p2, t)
        return x, y, math.atan2(ty, tx)


def _bezier(p0: Point, p1: Point, p2: Point, t: float) -> Point:
    a, b, c = (1 - t) ** 2, 2 * (1 - t) * t, t * t
    return a * p0[0] + b * p1[0] + c * p2[0], a * p0[1] + b * p1[1] + c * p2[1]


def _curvature(p0: Point, p1: Point, p2: Point, t: float) -> float:
    dx, dy = _tangent(p0, p1, p2, t)
    ddx, ddy = 2 * (p0[0] - 2 * p1[0] + p2[0]), 2 * (p0[1] - 2 * p1[1] + p2[1])
    speed = math.hypot(dx, dy)
    return 0.0 if speed < 1e-9 else abs(dx * ddy - dy * ddx) / speed ** 3


def _tangent(p0: Point, p1: Point, p2: Point, t: float) -> Point:
    tx = 2 * ((1 - t) * (p1[0] - p0[0]) + t * (p2[0] - p1[0]))
    ty = 2 * ((1 - t) * (p1[1] - p0[1]) + t * (p2[1] - p1[1]))
    if abs(tx) < 1e-9 and abs(ty) < 1e-9:  # degenerate (p0 == p1 == p2)
        return p2[0] - p0[0] or 1.0, p2[1] - p0[1]
    return tx, ty
