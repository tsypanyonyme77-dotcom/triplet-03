"""How likely is a perimeter to hold when travel times are not exactly as planned?

Each unit's and the suspect's travel time is multiplied by a lognormal factor with mean one (so the plan's times are the average, not a
best case); a draw succeeds when every held zone is still reached before the suspect gets there. Fixed seed, so the same plan gives the
same number.
"""

from __future__ import annotations

import math
import random

from brain.engines.perimeter import MARGIN_S, Perimeter


def robust(plan: Perimeter, *, sigma: float, draws: int = 200, seed: int = 1, margin_s: float = MARGIN_S) -> float:
    if not plan.zones:
        return 0.0
    rng = random.Random(seed)
    mu = -sigma * sigma / 2
    wins = 0
    for _ in range(draws):
        wins += all(plan.unit_eta_s[z] * math.exp(rng.gauss(mu, sigma)) + margin_s <= plan.suspect_eta_s[z] * math.exp(rng.gauss(mu, sigma)) for z in plan.zones)
    return round(wins / draws, 3)
