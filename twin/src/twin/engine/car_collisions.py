"""Car-car collision test: two oriented rectangles (car bodies) overlapping.

A body is length x width behind its front bumper point, along its heading (the
sim tracks the front bumper, see accidents.py). Separating axis theorem: two
convex shapes are apart if and only if their projections are apart on one of
the shapes' edge normals; a rectangle has two.
"""
from __future__ import annotations

import math

from twin.engine.accidents import CAR_WIDTH_M

Point = tuple[float, float]


def body_corners(front_x: float, front_y: float, heading: float, length: float, width: float = CAR_WIDTH_M) -> list[Point]:
    ux, uy = math.cos(heading), math.sin(heading)
    lx, ly = -uy * width / 2, ux * width / 2  # half width to the left
    rear_x, rear_y = front_x - ux * length, front_y - uy * length
    return [
        (front_x + lx, front_y + ly),
        (front_x - lx, front_y - ly),
        (rear_x - lx, rear_y - ly),
        (rear_x + lx, rear_y + ly),
    ]


def _axes(corners: list[Point]) -> list[Point]:
    (ax, ay), (bx, by), (cx, cy) = corners[0], corners[1], corners[2]
    return [(bx - ax, by - ay), (cx - bx, cy - by)]


def overlap_depth(a: list[Point], b: list[Point]) -> float:
    """Smallest penetration (m) of two rectangles over all separating axes; <= 0 if apart."""
    depth = math.inf
    for ax, ay in _axes(a) + _axes(b):
        norm = math.hypot(ax, ay)
        if norm < 1e-9:
            continue
        ax, ay = ax / norm, ay / norm
        pa = [x * ax + y * ay for x, y in a]
        pb = [x * ax + y * ay for x, y in b]
        depth = min(depth, min(max(pa), max(pb)) - max(min(pa), min(pb)))
        if depth <= 0:
            return depth
    return depth
