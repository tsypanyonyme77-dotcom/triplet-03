"""Forward models: what each numeric sensor usually says, and when a reading does not fit.

Per (sensor, field) the Brain keeps a running mean and variance. A reading many spreads away from
what the history predicts is a *surprise*. The first of a run is *doubted* (the Guardian may have
trusted it, but nothing yet agrees with it); the next one in the same direction confirms it; three
in a row mean the city has a new normal and the model starts again from there. A surprising reading
never moves the baseline, so a spoofed spike cannot teach the Brain that the spike is normal.

Only readings the Guardian trusted teach a baseline. A reading it did not trust is still compared with the
baseline (and may be reported as a surprise), but it never learns, never counts toward a new normal, and so
a slow ramp from a sensor nobody vouches for cannot walk the baseline away. A bounded history of what each
baseline learned lets a retracted reading be forgotten: the baseline is rebuilt without it.
"""

from __future__ import annotations

import math
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime

from pydantic import BaseModel

from brain.config import ForwardPolicy
from brain.contracts import SensorReading

# Only environmental sensors: a forward model of people would be a model of identities.
MODELLED: dict[str, list[str]] = {
    "traffic_camera": ["congestion_score", "avg_speed_kmh", "vehicle_count"],
    "water_level": ["level_m", "flow_rate_m3s"],
    "power_load": ["load_kw", "voltage_v"],
    "air_quality": ["aqi", "pm25_ugm3", "pm10_ugm3"],
}


@dataclass(frozen=True)
class Surprise:
    sensor_id: str
    field: str
    observed: float
    expected: float
    spread: float
    z: float
    run: int
    doubted: bool
    rebaselined: bool
    trusted: bool = True
    threshold: float = 4.0
    recovered: bool = False
    explained: str | None = None  # the Brain's own action (by name) that is known to cause this change
    kind: str = "self"  # `neighbour`: the sensor disagrees with a coupled partner, though its own history is unremarkable
    neighbour: str | None = None


@dataclass
class _Model:
    n: int = 0
    mean: float = 0.0
    var: float = 0.0
    run: int = 0
    direction: int = 0
    run_readings: list[str] | None = None
    run_values: list[float] = field(default_factory=list)
    history: deque = field(default_factory=deque)  # (reading_id, value) of what this baseline learned, newest last
    scores: deque = field(default_factory=deque)  # signed z of the trusted readings that were not surprising: what calibration reads
    prior: tuple[float, float, float] | None = None  # (mean, variance, spread) of the normal before the last accepted one
    prior_left: int = 0  # trusted readings before the remembered normal is forgotten
    thr: tuple[float, float] = (0.0, 0.0)  # calibrated thresholds (above, below), refreshed every few readings; 0 until there is history
    added: int = 0


@dataclass
class Expectation:
    """A change the Brain's own action is known to cause: in this zone, in this kind of sensor and field, in this direction, in this window."""

    zone: str
    sensor_type: str
    field: str
    direction: int
    start: datetime
    end: datetime
    action: str


class ForwardModels:
    def __init__(self, policy: ForwardPolicy) -> None:
        self.policy = policy
        self._expected: list[Expectation] = []
        self._models: dict[tuple[str, str], _Model] = {}
        self._doubted: set[str] = set()
        self._disputed: dict[str, None] = {}  # insertion-ordered, bounded
        self._z: dict[str, float] = {}

    def is_doubted(self, reading_id: str) -> bool:
        return reading_id in self._doubted or reading_id in self._disputed

    def dispute(self, reading_id: str) -> None:
        """A coupled partner disagrees with this reading: hold it as doubted for as long as the disagreement lasts."""
        self._disputed[reading_id] = None
        while len(self._disputed) > 10_000:
            self._disputed.pop(next(iter(self._disputed)))

    def strongest_z(self, reading_ids: Iterable[str]) -> float:
        return max((self._z.get(reading_id, 0.0) for reading_id in reading_ids), default=0.0)

    def _spread(self, model: _Model, field: str) -> float:
        floor = max(self.policy.min_spread.get(field, 0.0), self.policy.relative_spread * abs(model.mean))
        return max(math.sqrt(model.var), floor)

    def _learn(self, model: _Model, x: float, reading_id: str | None = None) -> None:
        frozen = self.policy.freeze_spread and model.n >= self.policy.warmup
        model.n += 1
        # A plain average while the history is short; afterwards at `alpha`. A frozen spread stops growing once warmed up,
        # so a slow drift cannot inflate the spread it is measured against.
        weight = self.policy.alpha if frozen else max(self.policy.alpha, 1 / model.n)
        delta = x - model.mean
        model.mean += weight * delta
        if not frozen:
            model.var = (1 - weight) * (model.var + weight * delta * delta)
        if reading_id is not None:
            model.history.append((reading_id, x))
            while len(model.history) > self.policy.history:
                model.history.popleft()

    def expect(self, zone: str, sensor_type: str, field_name: str, direction: int, start: datetime, end: datetime, action: str) -> None:
        """The Brain just acted: tell the models what to expect, so the effect of its own action is not read as a surprise."""
        self._expected.append(Expectation(zone, sensor_type, field_name, direction, start, end, action))

    def _explanation(self, reading: SensorReading, field_name: str, x: float, mean: float) -> str | None:
        for e in self._expected:
            if (e.zone == reading.zone_id and e.sensor_type == reading.type and e.field == field_name
                    and e.start <= reading.timestamp <= e.end and (x - mean) * e.direction > 0):
                return e.action
        return None

    def threshold(self, sensor_id: str, field_name: str, above: bool = True) -> float:
        """How many spreads off counts as a surprise for this sensor and field now, on the high side or the low side."""
        model = self._models.get((sensor_id, field_name))
        return self.policy.z_threshold if model is None else self._threshold(model, above)

    def _threshold(self, model: _Model, above: bool) -> float:
        if self.policy.calibration != "quantile" or len(model.scores) < self.policy.calibration_min or model.thr[0] <= 0:
            return self.policy.z_threshold
        return model.thr[0] if above else model.thr[1]

    def _calibrate(self, model: _Model, signed_z: float) -> None:
        """Remember an ordinary reading's signed z; each side's threshold follows how heavy that side's tail is.

        Every trusted reading counts, surprises too (clipped at max_z), because a sensor whose tail is heavy shows it in
        the readings that cross the line. One spike cannot lift a 99th percentile, and a run that becomes a new normal
        is wiped when it is accepted. A side's threshold is z_threshold scaled by how far that side's 99th-percentile z
        sits above a Gaussian's 2.576, so a sensor that wobbles upward more than downward gets a higher line upward
        only. It never drops below z_threshold and never rises past max_z: someone who feeds a trusted sensor enough
        large readings can desensitise it up to that cap and no further.
        """
        if self.policy.calibration != "quantile":
            return
        model.scores.append(signed_z)
        while len(model.scores) > self.policy.calibration_window:
            model.scores.popleft()
        model.added += 1
        if len(model.scores) >= self.policy.calibration_min and (model.thr[0] <= 0 or model.added % 10 == 0):
            ordered = sorted(model.scores)
            top = ordered[int(0.99 * (len(ordered) - 1))]
            bottom = -ordered[int(0.01 * (len(ordered) - 1))]
            model.thr = tuple(min(max(self.policy.z_threshold * tail / 2.576, self.policy.z_threshold), self.policy.max_z) for tail in (top, bottom))

    def baseline(self, sensor_id: str, field_name: str) -> tuple[float, float] | None:
        """What the model expects of this sensor and field now, and how far it may stray: (mean, spread)."""
        model = self._models.get((sensor_id, field_name))
        return None if model is None or model.n == 0 else (model.mean, self._spread(model, field_name))

    def history_length(self, sensor_id: str, field_name: str) -> int:
        model = self._models.get((sensor_id, field_name))
        return 0 if model is None else len(model.history)

    def forget(self, reading_id: str) -> list[tuple[str, str]]:
        """Take a retracted reading out of what the baselines learned. Returns the (sensor, field) pairs rebuilt.

        A baseline is rebuilt by learning its remaining history again, in order. A reading older than the history
        has already faded out of the running mean, so there is nothing to rebuild. A reading that is part of a
        surprise run leaves the run, and the run starts again from what is left of it.
        """
        self._doubted.discard(reading_id)
        self._disputed.pop(reading_id, None)
        self._z.pop(reading_id, None)
        rebuilt = []
        for (sensor_id, field_name), model in self._models.items():
            if model.run_readings and reading_id in model.run_readings:
                kept = [(r, v) for r, v in zip(model.run_readings, model.run_values, strict=True) if r != reading_id]
                model.run_readings = [r for r, _ in kept] or None
                model.run_values = [v for _, v in kept]
                model.run = len(kept)
                if not kept:
                    model.direction = 0
            if any(r == reading_id for r, _ in model.history):
                remaining = [(r, v) for r, v in model.history if r != reading_id]
                model.n, model.mean, model.var = 0, 0.0, 0.0
                model.history = deque()
                for r, v in remaining:
                    self._learn(model, v, r)
                rebuilt.append((sensor_id, field_name))
        return rebuilt

    def observe(self, reading: SensorReading, value: BaseModel, trusted: bool = True) -> list[Surprise]:
        found = []
        if self._expected:
            self._expected = [e for e in self._expected if e.end >= reading.timestamp]
        for name in MODELLED.get(reading.type, []):
            x = getattr(value, name, None)
            if x is None or isinstance(x, bool):
                continue
            model = self._models.setdefault((reading.sensor_id, name), _Model())
            if model.n < self.policy.warmup:
                if trusted:
                    self._learn(model, float(x), reading.reading_id)
                continue
            spread = self._spread(model, name)
            z = abs(x - model.mean) / spread
            limit = self._threshold(model, x >= model.mean)
            if trusted and model.prior is not None:
                model.prior_left -= 1
                if model.prior_left <= 0:
                    model.prior = None
            if z < limit:
                if trusted:
                    signed = (x - model.mean) / spread
                    model.run, model.run_readings, model.run_values = 0, None, []
                    self._learn(model, float(x), reading.reading_id)
                    self._calibrate(model, signed)
                continue
            if trusted:
                self._calibrate(model, max(min((x - model.mean) / spread, self.policy.max_z), -self.policy.max_z))
            if trusted and self._expected and (action := self._explanation(reading, name, float(x), model.mean)) is not None:
                # The Brain did this itself and knew what it would cause: follow the change, no doubt, no wait.
                expected = model.mean
                model.mean, model.var = float(x), 0.0
                model.run, model.run_readings, model.run_values, model.direction = 0, None, [], 0
                model.history = deque([(reading.reading_id, float(x))])
                model.scores, model.thr = deque(), (0.0, 0.0)
                self._doubted.discard(reading.reading_id)
                found.append(Surprise(reading.sensor_id, name, float(x), round(expected, 4), round(spread, 4), round(z, 2),
                                      run=1, doubted=False, rebaselined=False, threshold=round(limit, 2), explained=action))
                continue
            if trusted and self.policy.recover and model.prior is not None:
                prior_mean, prior_var, prior_spread = model.prior
                if abs(x - prior_mean) / prior_spread < self.policy.z_threshold / 2:
                    # Back to a level this sensor was already known to have: not a new surprise, so no doubt and no wait.
                    # The level it leaves becomes the remembered one, so a sensor that flaps between two is not doubted each time.
                    expected = model.mean
                    model.prior = (model.mean, model.var, spread)
                    model.prior_left = self.policy.calibration_window
                    model.mean, model.var = prior_mean, prior_var
                    model.run, model.run_readings, model.run_values, model.direction = 0, None, [], 0
                    model.history = deque([(reading.reading_id, float(x))])
                    model.scores, model.thr = deque(), (0.0, 0.0)
                    self._doubted.discard(reading.reading_id)
                    found.append(Surprise(reading.sensor_id, name, float(x), round(expected, 4), round(spread, 4), round(z, 2),
                                          run=1, doubted=False, rebaselined=False, threshold=round(limit, 2), recovered=True))
                    continue
            if not trusted:
                # Compared, reported, never learned from: it cannot start a run, join one, or become a new normal.
                self._z[reading.reading_id] = max(self._z.get(reading.reading_id, 0.0), round(z, 2))
                found.append(Surprise(reading.sensor_id, name, float(x), round(model.mean, 4), round(spread, 4), round(z, 2),
                                      run=1, doubted=True, rebaselined=False, trusted=False, threshold=round(limit, 2)))
                continue

            direction = 1 if x > model.mean else -1
            if model.run and direction == model.direction:
                model.run += 1
            else:
                model.run, model.direction, model.run_readings, model.run_values = 1, direction, [], []
            model.run_readings.append(reading.reading_id)
            model.run_values.append(float(x))
            expected, rebaselined = model.mean, model.run >= self.policy.adopt_after
            if model.run >= 2:
                self._doubted.difference_update(model.run_readings)
            if rebaselined:
                model.prior, model.prior_left = (model.mean, model.var, spread), self.policy.calibration_window
                # The accepted run is the new normal: the history starts again from it.
                model.history = deque(zip(model.run_readings, model.run_values, strict=True))
                model.mean, model.var, model.run, model.run_readings, model.run_values = float(x), 0.0, 0, None, []
                model.scores, model.thr = deque(), (0.0, 0.0)  # a new normal: calibrate again from its own readings
            elif model.run == 1:
                self._doubted.add(reading.reading_id)
            self._z[reading.reading_id] = max(self._z.get(reading.reading_id, 0.0), round(z, 2))
            found.append(Surprise(
                reading.sensor_id, name, float(x), round(expected, 4), round(spread, 4), round(z, 2),
                run=self.policy.adopt_after if rebaselined else model.run,
                doubted=not rebaselined and model.run == 1, rebaselined=rebaselined, threshold=round(limit, 2),
            ))
        return found
