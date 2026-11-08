"""Which way a pedestrian's body faces, separately from how it moves.

The movement model (social_force.py) gives a velocity; facing straight along it makes
the body spin whenever the velocity is small or reverses: nudged apart by a neighbour,
settling at a kerb, stepping back or aside in a crowd. People do not turn around for
that. So:
  - waiting at a kerb, a pedestrian faces across the crosswalk;
  - walking, they face their walking direction only when it leads toward the goal
    (within FACE_VELOCITY_DEG); stepping aside or back, they keep facing the goal;
  - below MIN_SPEED_MS the velocity direction is noise, so the facing stays put;
  - the body turns toward that facing at most MAX_TURN_DEG_S, never snapping.
"""
from __future__ import annotations

import math

MIN_SPEED_MS = 0.3          # slower than this is shuffling or being nudged
FACE_VELOCITY_DEG = 60.0    # face the walking direction only within this of the goal direction
MAX_TURN_DEG_S = 180.0      # a brisk turn of the body


def angle_diff(a: float, b: float) -> float:
    """Shortest signed angle from a to b, in (-pi, pi]."""
    return math.atan2(math.sin(b - a), math.cos(b - a))


def walking_facing(vx: float, vy: float, to_goal_x: float, to_goal_y: float) -> float | None:
    """Facing a walking pedestrian turns toward, or None to keep the current one."""
    if math.hypot(vx, vy) <= MIN_SPEED_MS:
        return None
    moving = math.atan2(vy, vx)
    if math.hypot(to_goal_x, to_goal_y) < 1e-6:
        return moving
    goal = math.atan2(to_goal_y, to_goal_x)
    return moving if abs(angle_diff(moving, goal)) <= math.radians(FACE_VELOCITY_DEG) else goal


def turn_toward(heading: float, target: float, dt: float) -> float:
    """`heading` turned toward `target` by at most MAX_TURN_DEG_S * dt, wrapped to (-pi, pi]."""
    step = math.radians(MAX_TURN_DEG_S) * dt
    turned = heading + max(-step, min(step, angle_diff(heading, target)))
    return math.atan2(math.sin(turned), math.cos(turned))
