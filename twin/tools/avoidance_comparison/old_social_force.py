"""Social Force Model (Helbing & Molnar) for pedestrian movement.

Each pedestrian is a point mass subject to summed forces each tick:
  - a driving force toward its current goal point (desired speed + direction)
  - a repulsive force from every other nearby pedestrian (personal space)
  - a repulsive force from the road edge it's walking beside (stay off the street)
Sum -> acceleration -> integrate velocity/position. Standard formulation,
tuned for a sidewalk-width lane rather than open-plaza crowds.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

DESIRED_SPEED_MS = 1.4          # average adult walking speed
RELAXATION_TIME_S = 0.5           # how quickly velocity catches up to the desired direction/speed
PED_REPULSION_STRENGTH = 2.0        # magnitude of the pairwise avoidance force
PED_REPULSION_RANGE_M = 1.2          # decay range of pairwise avoidance
PED_INTERACTION_RADIUS_M = 4.0        # ignore pedestrians farther than this (perf + realism)
BODY_RADIUS_M = 0.3                     # personal space radius, used for hard-contact push-back
SIDESTEP_BIAS = 0.5                       # lateral "step right to pass" bias, breaks head-on standoffs
EDGE_REPULSION_STRENGTH = 3.0             # push back toward the walkway, away from the road/obstacle edge
EDGE_REPULSION_RANGE_M = 0.6


@dataclass
class SocialForceState:
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0


def _driving_force(state: SocialForceState, goal_x: float, goal_y: float) -> tuple[float, float]:
    dx, dy = goal_x - state.x, goal_y - state.y
    dist = math.hypot(dx, dy)
    if dist < 1e-6:
        desired_vx, desired_vy = 0.0, 0.0
    else:
        desired_vx = (dx / dist) * DESIRED_SPEED_MS
        desired_vy = (dy / dist) * DESIRED_SPEED_MS
    return (
        (desired_vx - state.vx) / RELAXATION_TIME_S,
        (desired_vy - state.vy) / RELAXATION_TIME_S,
    )


def _pairwise_repulsion(
    state: SocialForceState, others: list[SocialForceState]
) -> tuple[float, float]:
    fx, fy = 0.0, 0.0
    for other in others:
        dx, dy = state.x - other.x, state.y - other.y
        dist = math.hypot(dx, dy)
        if dist > PED_INTERACTION_RADIUS_M:
            continue
        if dist < 1e-6:
            # exact overlap (or a perfectly head-on approach collapsing the gap to zero):
            # nudge apart on a stable, id-independent axis so both sides push the same way
            # and don't lock into a symmetric standoff
            dx, dy = 1.0, 0.0
            dist = 1.0
        overlap = BODY_RADIUS_M * 2 - dist
        magnitude = PED_REPULSION_STRENGTH * math.exp(overlap / PED_REPULSION_RANGE_M)
        # hard-contact push-back if bodies actually overlap, on top of the smooth field
        if overlap > 0:
            magnitude += EDGE_REPULSION_STRENGTH * overlap
        fx += magnitude * dx / dist
        fy += magnitude * dy / dist

        # lateral "step to your own right" bias, scaled by the same closeness factor:
        # breaks the head-on standoff where two people on a collinear path both push
        # straight back along their shared axis and never actually go around each other
        speed = math.hypot(state.vx, state.vy)
        if speed > 1e-6:
            right_x, right_y = state.vy / speed, -state.vx / speed
            closeness = math.exp(overlap / PED_REPULSION_RANGE_M)
            fx += SIDESTEP_BIAS * closeness * right_x
            fy += SIDESTEP_BIAS * closeness * right_y
    return fx, fy


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
) -> None:
    """Mutates `state` in place: applies one tick of Social Force integration."""
    fx, fy = _driving_force(state, goal_x, goal_y)
    rx, ry = _pairwise_repulsion(state, nearby)
    fx += rx
    fy += ry

    if walkway_perp is not None:
        ex, ey = _edge_repulsion(state, walkway_signed_offset, *walkway_perp)
        fx += ex
        fy += ey

    state.vx += fx * dt
    state.vy += fy * dt

    speed = math.hypot(state.vx, state.vy)
    max_speed = DESIRED_SPEED_MS * 1.3
    if speed > max_speed:
        state.vx = state.vx / speed * max_speed
        state.vy = state.vy / speed * max_speed

    state.x += state.vx * dt
    state.y += state.vy * dt
