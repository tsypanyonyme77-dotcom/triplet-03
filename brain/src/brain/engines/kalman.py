"""A level tracker: how fast is it rising, and when will it cross the line, with an interval.

A constant-velocity Kalman filter over (level, rate). A static threshold tells you the river is over the line; this says it will be
in 14 minutes, give or take 3, early enough to act. It learns only from trusted readings (an untrusted one is compared and reported,
never taught), damps a single spike instead of extrapolating it, and rebuilds from the readings it kept when one is retracted.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

SPIKE_SIGMAS = 3.0  # an innovation beyond this many standard deviations is clipped to it
SLOPE_SIGMAS = 2.0  # the rate must be this far from zero before a time to threshold is claimed


@dataclass(frozen=True)
class TimeTo:
    mean_s: float  # infinity when the level is not demonstrably moving toward the threshold
    sd_s: float
    p_within: Callable[[float], float]


class LevelTracker:
    def __init__(self, process_var: float = 1e-9, measurement_var: float = 1e-3) -> None:
        self.q, self.r = process_var, measurement_var
        self._kept: list[tuple[float, float]] = []  # trusted (t, level), for a rebuild
        self._reset()

    def _reset(self) -> None:
        self.t: float | None = None
        self.x = [0.0, 0.0]  # level, rate per second
        self.p = [[1.0, 0.0], [0.0, 1.0]]
        self.damped = 0

    def update(self, t_s: float, level: float, trusted: bool = True) -> None:
        if not trusted:
            return
        self._kept.append((t_s, level))
        self._step(t_s, level)

    def _step(self, t_s: float, level: float) -> None:
        if self.t is None:
            self.x, self.t = [level, 0.0], t_s
            self.p = [[self.r, 0.0], [0.0, 1e-2]]
            return
        dt = max(t_s - self.t, 1e-9)
        x0, x1 = self.x[0] + self.x[1] * dt, self.x[1]
        (a, b), (c, d) = self.p
        p00 = a + dt * (b + c) + dt * dt * d + self.q * dt ** 3 / 3
        p01 = b + dt * d + self.q * dt ** 2 / 2
        p10 = c + dt * d + self.q * dt ** 2 / 2
        p11 = d + self.q * dt
        s = p00 + self.r
        innovation = level - x0
        limit = SPIKE_SIGMAS * math.sqrt(s)
        if abs(innovation) > limit:
            innovation, self.damped = math.copysign(limit, innovation), self.damped + 1
        k0, k1 = p00 / s, p10 / s
        self.x = [x0 + k0 * innovation, x1 + k1 * innovation]
        self.p = [[(1 - k0) * p00, (1 - k0) * p01], [p10 - k1 * p00, p11 - k1 * p01]]
        self.t = t_s

    def retract(self, t_s: float) -> None:
        """A reading was withdrawn: forget it and rebuild the state from the rest."""
        kept = [(t, v) for t, v in self._kept if t != t_s]
        self._kept = []
        self._reset()
        for t, v in kept:
            self.update(t, v)

    def state(self) -> tuple[float, float, float]:
        return self.x[0], self.x[1], self.p[1][1]

    def time_to(self, threshold: float) -> TimeTo:
        level, rate, var_rate = self.x[0], self.x[1], self.p[1][1]
        sd_rate = math.sqrt(max(var_rate, 1e-18))
        gap = threshold - level
        if gap <= 0:
            return TimeTo(0.0, 0.0, lambda h: 1.0)
        if rate <= 0 or rate < SLOPE_SIGMAS * sd_rate:
            return TimeTo(math.inf, math.inf, lambda h: 0.0)
        mean = gap / rate
        sd = math.sqrt((self.p[0][0] + mean * mean * var_rate) / (rate * rate))  # first-order spread of gap / rate
        return TimeTo(mean, sd, lambda horizon: 0.5 * (1 + math.erf((horizon - mean) / (sd * math.sqrt(2)))))
