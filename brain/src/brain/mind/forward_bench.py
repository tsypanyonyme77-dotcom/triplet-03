"""A benchmark for the forward models: synthetic sensor streams with a known truth.

Each stream is 1,000 readings of one water-level sensor at 0.30 m with a change (or none) at reading 500.
A configuration of the forward models is scored on how often it raises a surprise where nothing changed (false
doubts), how many readings it needs to accept a real step as the new normal (delay), whether it ever accepts a
lone spike (it must not), and what it does on a recovery. The same seed always gives the same streams: seeds
under 1000 are for design and tuning, seeds from 1000 are for the numbers that decide a default.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from statistics import mean

from brain.config import ForwardPolicy
from brain.contracts import CONTRACT_VERSION, SensorReading, WaterLevel
from brain.mind.forward import ForwardModels

LEVEL = 0.30
SPREAD = 0.03  # the spread floor for `level_m`: the unit the steps are measured in
NOISE = 0.01
LENGTH = 1000
CHANGE_AT = 500
BACK_AT = 700
T0 = datetime(2026, 11, 2, 14, 0, 0, tzinfo=UTC)

Stream = Callable[[int], list[float]]


def _gauss(rng: random.Random, scale: float = NOISE) -> float:
    return rng.gauss(0.0, scale)


def _student3(rng: random.Random, scale: float = NOISE) -> float:
    chi = sum(rng.gauss(0.0, 1.0) ** 2 for _ in range(3))
    return rng.gauss(0.0, 1.0) / math.sqrt(chi / 3) * scale


def _stream(shape: Callable[[int], float], noise: Callable[[random.Random], float] = _gauss) -> Stream:
    def make(seed: int) -> list[float]:
        rng = random.Random(seed)
        return [round(max(LEVEL + shape(i) + noise(rng), 0.0), 4) for i in range(LENGTH)]
    return make


def _step(spreads: float) -> Callable[[int], float]:
    return lambda i: spreads * SPREAD if i >= CHANGE_AT else 0.0


STREAMS: dict[str, Stream] = {
    "calm": _stream(lambda i: 0.0),
    # As noisy as the spread floor itself: the stream on which a lower threshold has a price.
    "noisy": _stream(lambda i: 0.0, lambda rng: _gauss(rng, 3 * NOISE)),
    "heavy": _stream(lambda i: 0.0, _student3),
    "skewed": _stream(lambda i: 0.0, lambda rng: NOISE * 1.5 * (math.exp(0.9 * rng.gauss(0, 1)) - math.exp(0.405))),
    "season": _stream(lambda i: 4 * SPREAD * math.sin(2 * math.pi * i / LENGTH)),
    "step_s": _stream(_step(5)),
    "step_m": _stream(_step(10)),
    "step_l": _stream(_step(20)),
    "step_back": _stream(lambda i: 10 * SPREAD if CHANGE_AT - 100 <= i < BACK_AT else 0.0),
    "spike": _stream(lambda i: 20 * SPREAD if i == CHANGE_AT else 0.0),
    "ramp": _stream(lambda i: 8 * SPREAD * min(max(i - CHANGE_AT, 0) / 400, 1.0)),
    # An attacker the Guardian trusts feeds a sensor a large reading in every fifty, then sends one 6-spread spike.
    "walk": _stream(lambda i: (7.5 * SPREAD if i % 50 == 0 and i < CHANGE_AT else 0.0) + (6 * SPREAD if i == CHANGE_AT else 0.0)),
}


def _readings(values: list[float]):
    for i, level in enumerate(values, start=1):
        value = WaterLevel(level_m=level)
        reading = SensorReading(contract_version=CONTRACT_VERSION, sensor_id="wl-bench", type="water_level", zone_id="zone-01",
                                timestamp=T0 + timedelta(seconds=i), sequence_no=i, value={"level_m": level})
        yield i - 1, reading, value


def run(policy: ForwardPolicy, values: list[float]):
    """Feed one stream through fresh forward models; returns what was reported at each reading index."""
    models = ForwardModels(policy)
    reported = {}
    for index, reading, value in _readings(values):
        found = models.observe(reading, value, trusted=True)
        if found:
            reported[index] = found
    return reported


def _score_stream(name: str, policy: ForwardPolicy, seed: int) -> dict:
    reported = run(policy, STREAMS[name](seed))
    if name in ("calm", "noisy", "heavy", "skewed", "season"):
        return {"false_doubts_per_1000": len(reported) * 1000 / LENGTH}
    if name.startswith("step_") and name != "step_back":
        accepted = [i for i, found in reported.items() if i >= CHANGE_AT and any(s.rebaselined for s in found)]
        return {"delay": (min(accepted) - CHANGE_AT + 1) if accepted else None}
    if name == "step_back":
        up = [i for i, found in reported.items() if i >= CHANGE_AT - 100 and any(s.rebaselined for s in found)]
        down_false = [i for i, found in reported.items() if i >= BACK_AT and any(s.doubted for s in found)]
        accepted_back = [i for i, found in reported.items() if i >= BACK_AT and any(s.rebaselined or getattr(s, "recovered", False) for s in found)]
        return {"delay": (min(up) - (CHANGE_AT - 100) + 1) if up else None, "recovery_false_doubts": len(down_false),
                "recovery_delay": (min(accepted_back) - BACK_AT + 1) if accepted_back else None}
    if name == "spike":
        adopted = any(s.rebaselined for i, found in reported.items() if i >= CHANGE_AT for s in found)
        return {"spike_adopted": int(adopted), "spike_reported": int(CHANGE_AT in reported)}
    if name == "ramp":
        return {"ramp_alarms": len([i for i in reported if i >= CHANGE_AT])}
    if name == "walk":
        return {"walk_spike_reported": int(CHANGE_AT in reported)}
    raise KeyError(name)


def score(policy: ForwardPolicy, seeds) -> dict[str, dict]:
    """Per stream, each metric averaged over the seeds (`None` when a metric was missed on any seed)."""
    result: dict[str, dict] = {}
    for name in STREAMS:
        rows = [_score_stream(name, policy, seed) for seed in seeds]
        result[name] = {key: (None if any(r[key] is None for r in rows) else round(mean(r[key] for r in rows), 2)) for key in rows[0]}
    return result


def table(scores: dict[str, dict]) -> str:
    lines = ["| stream | result |", "| --- | --- |"]
    for name, metrics in scores.items():
        lines.append(f"| {name} | " + ", ".join(f"{key} {'never' if value is None else value}" for key, value in metrics.items()) + " |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------- injected anomalies

ANOMALY_AT = (150, 300, 450, 600, 750)
ANOMALY_SIZES = (4.5, 6.0, 10.0)  # in spreads: the smallest is only just over today's line


def lead_time(seeds, rate_m_per_min: float = 0.05, noise: float = 0.02, line: float = 1.0, start: float = 0.3, every_s: float = 10.0) -> dict:
    """A flood ramp with a known time of overflow: how many seconds before the static line is crossed does the Kalman tracker first say
    it will be crossed within 10 minutes with at least even odds? Positive is a warning ahead of the threshold; None means it never did."""
    from brain.engines.kalman import LevelTracker

    leads = []
    for seed in seeds:
        rng = random.Random(seed)
        tracker, crossed, warned = LevelTracker(measurement_var=noise * noise), (line - start) / (rate_m_per_min / 60), None
        t = 0.0
        while t <= crossed:
            tracker.update(t, start + rate_m_per_min / 60 * t + rng.gauss(0, noise))
            if warned is None and tracker.time_to(line).p_within(600.0) >= 0.5:
                warned = t
            t += every_s
        leads.append(None if warned is None else crossed - warned)
    found = [x for x in leads if x is not None]
    return {"seeds": len(leads), "warned": len(found), "mean_lead_s": round(sum(found) / len(found), 1) if found else None, "min_lead_s": round(min(found), 1) if found else None}


def anomaly_stream(size: float, seed: int) -> list[float]:
    """A calm stream with a single-reading spike of `size` spreads at each of ANOMALY_AT."""
    rng = random.Random(seed * 7919 + int(size * 10))
    return [round(max(LEVEL + (size * SPREAD if i in ANOMALY_AT else 0.0) + _gauss(rng), 0.0), 4) for i in range(LENGTH)]


def recall(policy: ForwardPolicy, seeds) -> float:
    """The share of injected anomalies the models report, over every size and seed. A tuned policy must not lose any."""
    seen = total = 0
    for seed in seeds:
        for size in ANOMALY_SIZES:
            reported = run(policy, anomaly_stream(size, seed))
            seen += sum(1 for i in ANOMALY_AT if i in reported)
            total += len(ANOMALY_AT)
    return seen / total
