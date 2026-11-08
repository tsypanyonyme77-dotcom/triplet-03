"""Anticipatory pedestrian avoidance: the time-to-collision power law.

Karamouzas, Skinner & Guy (2014), "Universal Power Law Governing Pedestrian
Interactions", Physical Review Letters 113, 238701.

Instead of pushing away based on current distance (classic Social Force),
each pedestrian reacts to how soon it would collide with a neighbour if both
kept their current velocities. The interaction energy is

    E(tau) = k / tau^2 * exp(-tau / tau0)

and the avoidance force on pedestrian A is -grad_{x_A} E. Because tau depends
on relative velocity as well as position, people start adjusting early and
smoothly, and stop reacting once they are on non-colliding paths, even when
they are close (e.g. walking side by side).

Pure maths, no simulation state: callers pass positions/velocities in and get
a force vector back. Explicit integration of this force is stiff (Karamouzas
et al. 2017, "Implicit Crowds"), so the caller should low-pass filter it over
time; social_force.step_pedestrian does.
"""
from __future__ import annotations

import math
from typing import Protocol

# From the paper's fit to real crowd data
TTC_STRENGTH_K = 1.5          # k, scales the whole interaction
TTC_HORIZON_S = 3.0             # tau0, collisions further out than ~this are mostly ignored

# Our tuning
SENSING_RADIUS_M = 6.0            # ignore neighbours farther than this (matches sim's neighbour box)
MIN_TTC_S = 0.05                    # floor on tau to keep the force finite right before contact
MAX_FORCE = 8.0                       # cap per-neighbour force magnitude (m/s^2), avoids blow-ups at tiny tau
CONTACT_STIFFNESS = 20.0               # push-back per metre of body overlap (bodies already touching)
TIE_BREAK_OFFSET_M = 0.05                # see _break_symmetry


class Kinematic(Protocol):
    x: float
    y: float
    vx: float
    vy: float


def avoidance_force(
    me: Kinematic, others: list[Kinematic], body_radius_m: float
) -> tuple[float, float]:
    """Summed avoidance force on `me` from all `others` (TTC interaction + contact)."""
    fx, fy = 0.0, 0.0
    combined_radius = 2 * body_radius_m
    for other in others:
        dx, dy = me.x - other.x, me.y - other.y          # x = x_A - x_B
        dist = math.hypot(dx, dy)
        if dist > SENSING_RADIUS_M:
            continue

        if dist < combined_radius:
            cx, cy = _contact_force(dx, dy, dist, combined_radius)
            fx += cx
            fy += cy
            continue

        rvx, rvy = me.vx - other.vx, me.vy - other.vy      # v = v_A - v_B
        dx, dy = _break_symmetry(dx, dy, rvx, rvy, me.vx, me.vy)
        tx, ty = _ttc_force(dx, dy, rvx, rvy, combined_radius)
        fx += tx
        fy += ty
    return fx, fy


def _ttc_force(
    dx: float, dy: float, rvx: float, rvy: float, combined_radius: float
) -> tuple[float, float]:
    """-grad E(tau) for one neighbour; zero if no collision is predicted ahead."""
    a = rvx * rvx + rvy * rvy
    if a < 1e-9:
        return 0.0, 0.0  # same velocity: the gap never changes
    b = dx * rvx + dy * rvy
    c = dx * dx + dy * dy - combined_radius * combined_radius
    discriminant = b * b - a * c
    if discriminant <= 0.0:
        return 0.0, 0.0  # paths never come within combined_radius
    d = math.sqrt(discriminant)
    tau = (-b - d) / a
    if tau <= 0.0:
        return 0.0, 0.0  # closest approach is in the past: moving apart
    tau = max(tau, MIN_TTC_S)

    # -E'(tau) = k e^{-tau/tau0} / tau^2 * (2/tau + 1/tau0)
    magnitude = (
        TTC_STRENGTH_K * math.exp(-tau / TTC_HORIZON_S) / (tau * tau)
        * (2.0 / tau + 1.0 / TTC_HORIZON_S)
    )
    # grad_x tau = (-v - (b v - a x) / d) / a
    gx = (-rvx - (b * rvx - a * dx) / d) / a
    gy = (-rvy - (b * rvy - a * dy) / d) / a
    fx, fy = magnitude * gx, magnitude * gy

    norm = math.hypot(fx, fy)
    if norm > MAX_FORCE:
        fx, fy = fx / norm * MAX_FORCE, fy / norm * MAX_FORCE

    # Grazing fade-out (our addition, not in the paper): the raw force peaks when
    # paths only just touch and then drops to zero once they clear, which makes
    # pedestrians chatter at a 0.1 s tick. Scale by sqrt(1 - (closest_approach / r)^2),
    # which is 1 for a dead-on collision and goes smoothly to 0 at a graze. Applied
    # after the cap so near-grazes stay weak even when the raw force is huge.
    graze_weight = d / math.sqrt(a) / combined_radius
    return fx * graze_weight, fy * graze_weight


def _contact_force(
    dx: float, dy: float, dist: float, combined_radius: float
) -> tuple[float, float]:
    """Linear push-back once bodies overlap (tau is undefined there)."""
    if dist < 1e-6:
        # exact overlap: separate on a fixed axis so both sides agree on the direction
        dx, dy, dist = 1.0, 0.0, 1.0
    overlap = combined_radius - dist
    magnitude = CONTACT_STIFFNESS * overlap
    return magnitude * dx / dist, magnitude * dy / dist


def _break_symmetry(
    dx: float, dy: float, rvx: float, rvy: float, vx: float, vy: float
) -> tuple[float, float]:
    """Perfectly collinear approach: the gradient has no sideways component, so
    both pedestrians would only brake and never go around. Treat the other as
    sitting a few cm to our left, which pushes us right; the other person does
    the same from their side, so both pass keeping right."""
    rel_speed = math.hypot(rvx, rvy)
    speed = math.hypot(vx, vy)
    if rel_speed < 1e-9 or speed < 1e-9:
        return dx, dy
    lateral = abs(dx * rvy - dy * rvx) / rel_speed  # distance of x from the relative-velocity line
    if lateral >= TIE_BREAK_OFFSET_M:
        return dx, dy
    right_x, right_y = vy / speed, -vx / speed
    return dx + right_x * TIE_BREAK_OFFSET_M, dy + right_y * TIE_BREAK_OFFSET_M
