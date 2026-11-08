"""Hard non-overlap for pedestrians.

The avoidance force (ttc_avoidance.py) steers people apart, but a force can only
make overlap unlikely, not impossible (crowds at a crossing, a runner overtaking).
After each integration step this projects any overlapping pair apart along the
line between their centres, split equally, so bodies never interpenetrate.
"""
from __future__ import annotations

import math
from typing import Protocol

ITERATIONS = 4  # a few passes settle chains of contacts (A pushes B into C)


class Positioned(Protocol):
    x: float
    y: float


def separate(bodies: list[Positioned], min_distance: float) -> bool:
    """Returns True if any body was moved."""
    any_moved = False
    for _ in range(ITERATIONS):
        moved = False
        for i, a in enumerate(bodies):
            for b in bodies[i + 1:]:
                dx, dy = b.x - a.x, b.y - a.y
                if abs(dx) >= min_distance or abs(dy) >= min_distance:
                    continue
                dist = math.hypot(dx, dy)
                if dist >= min_distance:
                    continue
                if dist < 1e-9:
                    dx, dy, dist = 1.0, 0.0, 1.0  # exact overlap: fixed axis, both agree
                push = (min_distance - dist) / 2 + 1e-4
                nx_, ny_ = dx / dist, dy / dist
                a.x -= nx_ * push
                a.y -= ny_ * push
                b.x += nx_ * push
                b.y += ny_ * push
                moved = True
        if not moved:
            return any_moved
        any_moved = True
    return any_moved
