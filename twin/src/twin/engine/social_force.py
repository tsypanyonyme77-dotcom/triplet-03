"""Pedestrian movement: force-based integration with anticipatory avoidance.

Each pedestrian is a point mass subject to summed forces each tick:
  - a driving force toward its current goal point (desired speed + direction),
    the Helbing & Molnar Social Force goal term
  - an avoidance force from nearby pedestrians, based on time-to-collision
    (Karamouzas et al. 2014 power law, see ttc_avoidance.py) instead of the
    classic distance-based social repulsion
  - a repulsive force from the road edge it's walking beside (stay off the street)
Sum -> acceleration -> integrate velocity/position.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from twin.engine.ttc_avoidance import avoidance_force

DESIRED_SPEED_MS = 1.4          # average adult walking speed
RELAXATION_TIME_S = 0.5           # how quickly velocity catches up to the desired direction/speed
BODY_RADIUS_M = 0.3                 # personal space radius used for collision prediction and contact
EDGE_REPULSION_STRENGTH = 3.0         # push back toward the walkway, away from the road/obstacle edge
EDGE_REPULSION_RANGE_M = 0.6
AVOIDANCE_SMOOTHING_S = 0.5               # time constant of the avoidance low-pass filter
ARRIVE_TIME_S = 1.0                         # stopping at a goal: aim to cover the rest in this long


@dataclass
class SocialForceState:
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    avoid_ax: float = 0.0   # low-pass filtered avoidance acceleration, see _filtered_avoidance
    avoid_ay: float = 0.0
    desired_speed: float = DESIRED_SPEED_MS  # per pedestrian: ~1.4 walking, ~3 running


def _driving_force(
    state: SocialForceState, goal_x: float, goal_y: float, stop_at_goal: bool = False
) -> tuple[float, float]:
    """Toward the goal at the desired speed. A pedestrian who has to stop at the goal
    (waiting at a kerb) slows down as it gets close instead: at full speed they would
    overshoot, turn back, overshoot again and spin around the point."""
    dx, dy = goal_x - state.x, goal_y - state.y
    dist = math.hypot(dx, dy)
    if dist < 1e-6:
        desired_vx, desired_vy = 0.0, 0.0
    else:
        speed = min(state.desired_speed, dist / ARRIVE_TIME_S) if stop_at_goal else state.desired_speed
        desired_vx = (dx / dist) * speed
        desired_vy = (dy / dist) * speed
    return (
        (desired_vx - state.vx) / RELAXATION_TIME_S,
        (desired_vy - state.vy) / RELAXATION_TIME_S,
    )


def _filtered_avoidance(
    state: SocialForceState, nearby: list[SocialForceState], dt: float
) -> tuple[float, float]:
    """Avoidance force smoothed with an exponential moving average. The raw
    time-to-collision force switches on and off between neighbours from tick to
    tick in crowds; filtering it removes the resulting zig-zag."""
    raw_ax, raw_ay = avoidance_force(state, nearby, BODY_RADIUS_M)
    blend = min(1.0, dt / AVOIDANCE_SMOOTHING_S)
    state.avoid_ax += blend * (raw_ax - state.avoid_ax)
    state.avoid_ay += blend * (raw_ay - state.avoid_ay)
    return state.avoid_ax, state.avoid_ay


def _edge_repulsion(
    state: SocialForceState, signed_dist_from_walkway_center: float, perp_x: float, perp_y: float
) -> tuple[float, float]:
    """Keeps pedestrians from drifting off the walkway strip (a soft wall on either side)."""
    half_width = 1.0  # walkway is ~2m wide before the repulsion kicks in
    penetration = abs(signed_dist_from_walkway_center) - half_width
    if penetration <= 0:
        return 0.0, 0.0
    direction = -1.0 if signed_dist_from_walkway_center > 0 else 1.0
    magnitude = EDGE_REPULSION_STRENGTH * math.exp(penetration / EDGE_REPULSION_RANGE_M)
    return magnitude * direction * perp_x, magnitude * direction * perp_y


def step_pedestrian(
    state: SocialForceState,
    goal_x: float,
    goal_y: float,
    nearby: list[SocialForceState],
    walkway_perp: tuple[float, float] | None,
    walkway_signed_offset: float,
    dt: float,
    stop_at_goal: bool = False,
) -> None:
    """Mutates `state` in place: applies one tick of force integration.
    `stop_at_goal`: slow down to stand at the goal instead of walking through it."""
    fx, fy = _driving_force(state, goal_x, goal_y, stop_at_goal)
    ax, ay = _filtered_avoidance(state, nearby, dt)
    fx += ax
    fy += ay

    if walkway_perp is not None:
        ex, ey = _edge_repulsion(state, walkway_signed_offset, *walkway_perp)
        fx += ex
        fy += ey

    state.vx += fx * dt
    state.vy += fy * dt

    speed = math.hypot(state.vx, state.vy)
    max_speed = state.desired_speed * 1.3
    if speed > max_speed:
        state.vx = state.vx / speed * max_speed
        state.vy = state.vy / speed * max_speed

    state.x += state.vx * dt
    state.y += state.vy * dt
