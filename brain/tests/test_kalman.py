"""The level tracker: a time to the line with an interval, learning only from trusted readings."""

import math
import random

from brain.engines.kalman import LevelTracker


def ramp(tracker, start=0.0, rate=0.002, seconds=300, step=10, noise=0.0, seed=1, trusted=True):
    rng = random.Random(seed)
    for t in range(0, seconds + 1, step):
        tracker.update(float(t), start + rate * t + rng.gauss(0, noise), trusted)


def test_a_steady_rise_gives_a_time_to_threshold_within_10_percent():
    tracker = LevelTracker(measurement_var=0.0004)
    ramp(tracker, noise=0.02)  # 0.002 m/s from 0 m; at 300 s it is at 0.6 m, so 2.0 m is 700 s further

    assert abs(tracker.time_to(2.0).mean_s - 700) / 700 < 0.10


def test_a_flat_series_gives_no_finite_time():
    tracker = LevelTracker(measurement_var=0.0004)
    ramp(tracker, rate=0.0, start=1.0, noise=0.02)

    assert math.isinf(tracker.time_to(2.0).mean_s)


def test_an_untrusted_reading_does_not_move_the_state():
    tracker = LevelTracker()
    ramp(tracker)
    before = tracker.state()
    tracker.update(310.0, 50.0, trusted=False)

    assert tracker.state() == before


def test_a_retracted_reading_is_forgotten_and_the_state_rebuilt():
    clean, dirty = LevelTracker(measurement_var=0.0004), LevelTracker(measurement_var=0.0004)
    ramp(clean)
    ramp(dirty)
    dirty.update(305.0, 9.0)
    dirty.retract(305.0)

    assert dirty.state() == clean.state()


def test_a_single_spike_is_damped_not_extrapolated():
    tracker = LevelTracker(measurement_var=0.0004)
    ramp(tracker, noise=0.01)
    tracker.update(310.0, 5.0)  # a spike 4 m above the line

    assert tracker.damped == 1 and tracker.state()[0] < 1.5


def test_the_estimate_carries_an_interval_that_widens_with_noise():
    quiet, noisy = LevelTracker(measurement_var=0.0004), LevelTracker(measurement_var=0.01)
    ramp(quiet, noise=0.02)
    ramp(noisy, noise=0.1)

    assert noisy.time_to(2.0).sd_s > quiet.time_to(2.0).sd_s > 0
    horizon = quiet.time_to(2.0).mean_s
    assert quiet.time_to(2.0).p_within(horizon + 3 * quiet.time_to(2.0).sd_s) > 0.99 > 0.01 > quiet.time_to(2.0).p_within(horizon - 3 * quiet.time_to(2.0).sd_s)


