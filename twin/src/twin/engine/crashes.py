"""Car-on-car collision chance.

IDM/MOBIL are collision-avoiding by construction, so a crash here isn't a
physics failure -- it's modeled as driver error: each tick, a following car
that's dangerously close to its leader (small gap, both still moving) has a
small chance of failing to brake in time. The base rate is deliberately tiny;
external events (heat waves, panic, etc.) scale it up via a multiplier the
simulation exposes, rather than a fixed higher constant, so "normal" driving
stays crash-free almost all the time.
"""
from __future__ import annotations

import random

BASE_CRASH_CHANCE_PER_TICK = 0.005  # 0.5%, scaled by the sim's current risk multiplier
CRASH_GAP_THRESHOLD_M = 1.5            # gap below this counts as "dangerously close"
CRASH_MIN_SPEED_MS = 3.0                 # below this speed a close gap is just queueing, not a near-miss


def should_crash(follower_speed: float, gap: float, risk_multiplier: float) -> bool:
    """Whether a following car crashes into its leader this tick.

    Only evaluated for gaps that are already dangerously small -- this models
    a failed emergency brake, not everyday close-following in traffic.
    """
    if gap > CRASH_GAP_THRESHOLD_M:
        return False
    if follower_speed < CRASH_MIN_SPEED_MS:
        return False
    chance = BASE_CRASH_CHANCE_PER_TICK * risk_multiplier
    return random.random() < chance
