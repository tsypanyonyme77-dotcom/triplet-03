"""Car-pedestrian collision test.

A car is an oriented rectangle behind its front bumper point (the sim tracks the
front: dist_on_edge and IDM gaps are front-bumper based); a pedestrian is a disc.
"""
from __future__ import annotations

import math

CAR_WIDTH_M = 2.0
MIN_IMPACT_SPEED_MS = 0.3   # a car creeping slower than this does not count as hitting someone


def car_hits_pedestrian(
    front_x: float,
    front_y: float,
    heading: float,
    length: float,
    px: float,
    py: float,
    radius: float,
    width: float = CAR_WIDTH_M,
) -> bool:
    ux, uy = math.cos(heading), math.sin(heading)
    rx, ry = px - front_x, py - front_y
    along = rx * ux + ry * uy                 # >0 ahead of the bumper, <0 along the body
    lateral = -rx * uy + ry * ux
    # closest point of the rectangle [−length, 0] x [−width/2, width/2] to the disc centre
    ca = min(max(along, -length), 0.0)
    cl = min(max(lateral, -width / 2), width / 2)
    return math.hypot(along - ca, lateral - cl) <= radius
