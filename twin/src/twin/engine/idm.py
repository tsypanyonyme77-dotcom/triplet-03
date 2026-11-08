"""Intelligent Driver Model (IDM) — car-following acceleration.

Standard microscopic traffic model. Each vehicle computes its own acceleration
from its speed, desired speed, and the gap/relative-speed to the vehicle ahead.
No lane-changing here (see mobil.py, not wired in for single-lane POC).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class IDMParams:
    v0: float = 13.9       # desired speed, m/s (~50 km/h)
    a: float = 1.2          # max acceleration, m/s^2
    b: float = 2.0          # comfortable braking deceleration, m/s^2
    s0: float = 2.0          # minimum gap at standstill, m
    T: float = 1.5            # desired time headway, s
    length: float = 4.5        # vehicle length, m


def idm_acceleration(
    v: float,
    v_lead: float | None,
    gap: float | None,
    params: IDMParams,
) -> float:
    """Compute acceleration for a vehicle at speed v.

    gap: bumper-to-bumper distance to the vehicle ahead (m), or None if no lead vehicle.
    v_lead: speed of the vehicle ahead (m/s), ignored if gap is None.
    """
    free_road_term = params.a * (1 - (max(v, 0.0) / params.v0) ** 4)

    if gap is None:
        return free_road_term

    dv = v - v_lead
    gap = max(gap, 0.01)
    s_star = params.s0 + max(
        0.0,
        v * params.T + (v * dv) / (2 * (params.a * params.b) ** 0.5),
    )
    interaction_term = params.a * (s_star / gap) ** 2
    return free_road_term - interaction_term


def step_vehicle(v: float, accel: float, dt: float) -> tuple[float, float]:
    """Integrate one tick. Returns (new_speed, distance_traveled)."""
    new_v = max(0.0, v + accel * dt)
    dist = v * dt + 0.5 * accel * dt * dt
    dist = max(0.0, dist)
    return new_v, dist
