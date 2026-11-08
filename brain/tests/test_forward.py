"""The forward models: what a sensor usually says, and when a reading does not fit."""

import random
from datetime import timedelta

from brain.config import ForwardPolicy
from brain.contracts import CONTRACT_VERSION, VALUE_MODELS, SensorReading
from brain.mind.forward import MODELLED, ForwardModels
from tests.conftest import T0


class Feed:
    """Readings from one water-level sensor, numbered like the Twin numbers them."""

    def __init__(self, models: ForwardModels, sensor="wl-01-01", type="water_level", field="level_m"):
        self.models, self.sensor, self.type, self.field, self.seq = models, sensor, type, field, 0

    def send(self, level: float, trusted: bool = True, **extra):
        self.seq += 1
        value = {self.field: level, **extra}
        reading = SensorReading(contract_version=CONTRACT_VERSION, sensor_id=self.sensor, type=self.type, zone_id="zone-01",
                                timestamp=T0 + timedelta(seconds=self.seq), sequence_no=self.seq, value=value)
        return reading, self.models.observe(reading, VALUE_MODELS[self.type].model_validate(value), trusted=trusted)

    def calm(self, count: int, level=0.30, noise=0.01, seed=1):
        rng = random.Random(seed)
        return [self.send(round(max(rng.gauss(level, noise), 0.0), 3)) for _ in range(count)]


def models(**changes) -> ForwardModels:
    return ForwardModels(ForwardPolicy(**changes))


def test_a_sensor_without_enough_history_is_never_surprising():
    feed = Feed(models())

    results = [feed.send(level)[1] for level in (0.3, 0.3, 2.5, 0.3)]  # warm-up is five readings

    assert results == [[], [], [], []]


def test_a_steady_sensor_with_ordinary_noise_is_never_surprising():
    feed = Feed(models())

    assert all(found == [] for _, found in feed.calm(200, noise=0.02))


def test_a_jump_far_outside_the_history_is_a_doubted_surprise():
    feed = Feed(models())
    feed.calm(10)

    reading, found = feed.send(2.4)

    (surprise,) = found
    assert surprise.sensor_id == "wl-01-01" and surprise.field == "level_m"
    assert surprise.observed == 2.4 and abs(surprise.expected - 0.30) < 0.02
    assert surprise.z >= 4 and surprise.run == 1 and surprise.doubted and not surprise.rebaselined
    assert feed.models.is_doubted(reading.reading_id)


def test_a_doubted_spike_does_not_move_the_baseline():
    feed = Feed(models())
    feed.calm(10)
    feed.send(2.4)

    _, found = feed.send(0.30)

    assert found == []


def test_a_second_surprise_in_the_same_direction_confirms_the_first():
    feed = Feed(models())
    feed.calm(10)
    first, _ = feed.send(1.1)

    second, found = feed.send(1.3)

    assert found[0].run == 2 and not found[0].doubted
    assert not feed.models.is_doubted(first.reading_id) and not feed.models.is_doubted(second.reading_id)


def test_three_consecutive_surprises_re_baseline_the_model():
    feed = Feed(models())
    feed.calm(10)
    feed.send(1.1)
    feed.send(1.2)
    _, found = feed.send(1.15)

    assert found[0].run == 3 and found[0].rebaselined and not found[0].doubted
    assert feed.send(1.16)[1] == []  # the new normal


def test_a_perfectly_flat_sensor_has_a_floor_on_its_spread():
    feed = Feed(models())
    for _ in range(10):
        feed.send(0.30)

    assert feed.send(0.31)[1] == []  # a hundredth of a metre is not a surprise even with zero variance
    assert feed.send(0.9)[1] != []


def test_a_spike_in_the_other_direction_starts_a_new_run():
    feed = Feed(models())
    feed.calm(10, level=1.0, noise=0.01)
    feed.send(2.5)

    _, found = feed.send(0.1)

    assert found[0].run == 1 and found[0].doubted


def test_citizen_activity_is_never_modelled():
    assert "citizen_activity" not in MODELLED and "emergency_call" not in MODELLED


def test_strongest_z_reports_the_largest_surprise_among_readings():
    feed = Feed(models())
    feed.calm(10)
    small, _ = feed.send(0.5)
    feed.send(0.30)
    big, _ = feed.send(3.0)
    models_ = feed.models

    assert models_.strongest_z([small.reading_id, big.reading_id]) > models_.strongest_z([small.reading_id]) > 0
    assert models_.strongest_z(["nothing#1"]) == 0.0


# --- readings the Guardian did not trust never teach the baseline ---------------------------------------------------


def test_a_distrusted_stream_never_moves_the_baseline():
    feed = Feed(models())
    feed.calm(20)

    for step in range(200):  # a slow, plausible ramp from a sensor nobody vouches for
        feed.send(0.30 + step * 0.0035, trusted=False)

    assert feed.send(0.30)[1] == []  # the baseline is still the calm one
    assert feed.send(0.9)[1] != []  # and a real jump is still a surprise


def test_a_distrusted_surprise_is_reported_but_never_adopted_as_a_new_normal():
    feed = Feed(models())
    feed.calm(10)

    found = [feed.send(2.4, trusted=False)[1] for _ in range(4)]

    assert all(len(f) == 1 and not f[0].rebaselined and not f[0].trusted for f in found)
    assert feed.send(0.30)[1] == []
    assert feed.send(2.4)[1][0].run == 1  # the trusted count starts from nothing: nothing distrusted counted toward it


def test_a_distrusted_reading_during_warm_up_does_not_count_toward_it():
    feed = Feed(models())

    for _ in range(20):
        feed.send(5.0, trusted=False)
    feed.calm(5)  # these five trusted readings are the whole history

    assert feed.models.baseline("wl-01-01", "level_m")[0] < 0.5


# --- forgetting a retracted reading ---------------------------------------------------------------------------------


def test_forgetting_a_reading_rebuilds_the_baseline_without_it():
    feed = Feed(models())
    feed.calm(30)
    before = feed.models.baseline("wl-01-01", "level_m")
    odd, found = feed.send(0.34)  # a bit high, but not a surprise: it is learned
    assert found == []
    assert feed.models.baseline("wl-01-01", "level_m")[0] > before[0]

    rebuilt = feed.models.forget(odd.reading_id)

    assert rebuilt == [("wl-01-01", "level_m")]
    after = feed.models.baseline("wl-01-01", "level_m")
    assert abs(after[0] - before[0]) < 0.003


def test_forgetting_a_reading_inside_a_surprise_run_ends_the_run():
    feed = Feed(models())
    feed.calm(10)
    spike, _ = feed.send(2.4)
    assert feed.models.is_doubted(spike.reading_id)

    feed.models.forget(spike.reading_id)

    assert not feed.models.is_doubted(spike.reading_id)
    again = feed.send(2.4)[1][0]
    assert again.run == 1 and again.doubted  # a fresh first surprise, not the confirmation of a forgotten one


def test_forgetting_a_reading_that_is_not_in_the_history_changes_nothing():
    feed = Feed(models(history=20))
    first, _ = feed.send(0.30)
    feed.calm(100)

    assert feed.models.forget(first.reading_id) == []
    assert feed.models.forget("nothing#1") == []


def test_the_history_is_bounded():
    feed = Feed(models(history=20))

    feed.calm(500)

    assert feed.models.history_length("wl-01-01", "level_m") == 20


# --- calibration: the threshold follows the sensor's own noise, upward only, and within a cap -------------------------


def heavy_feed(models_, count=600, seed=5, scale=0.02):
    """A feed with Student-t noise: far more large wobbles than a Gaussian with the same spread."""
    import math

    feed = Feed(models_)
    rng = random.Random(seed)
    out = []
    for _ in range(count):
        chi = sum(rng.gauss(0, 1) ** 2 for _ in range(3))
        out.append(feed.send(round(max(0.30 + rng.gauss(0, 1) / math.sqrt(chi / 3) * scale, 0.0), 4)))
    return feed, out


def test_the_calibrated_threshold_starts_at_the_fixed_one_and_never_goes_below_it():
    feed = Feed(models(calibration="quantile"))

    feed.calm(40)
    assert feed.models.threshold("wl-01-01", "level_m") == 4.0  # too little history to calibrate

    feed.calm(600, seed=2)
    assert feed.models.threshold("wl-01-01", "level_m") >= 4.0


def test_the_threshold_rises_on_a_sensor_with_heavy_tails_and_not_on_a_calm_one():
    heavy, _ = heavy_feed(models(calibration="quantile"))
    calm = Feed(models(calibration="quantile"))
    calm.calm(600, noise=0.02)

    assert heavy.models.threshold("wl-01-01", "level_m") > 4.1
    assert calm.models.threshold("wl-01-01", "level_m") == 4.0


def test_calibration_cuts_false_doubts_on_a_heavy_tailed_sensor():
    _, fixed = heavy_feed(models(calibration="fixed"), count=1500)
    _, tuned = heavy_feed(models(calibration="quantile"), count=1500)

    assert sum(1 for _, found in tuned if found) < sum(1 for _, found in fixed if found)


def test_a_real_step_is_still_caught_after_calibration():
    feed, _ = heavy_feed(models(calibration="quantile"))

    found = [feed.send(0.30 + 0.45)[1] for _ in range(3)]  # a 15-spread step

    assert found[0] and found[0][0].doubted and found[2][0].rebaselined


def test_a_lone_spike_does_not_move_the_threshold():
    feed = Feed(models(calibration="quantile"))
    feed.calm(600, noise=0.01)
    before = feed.models.threshold("wl-01-01", "level_m")

    feed.send(5.0)
    feed.calm(5)

    assert feed.models.threshold("wl-01-01", "level_m") == before


def test_an_attacker_who_keeps_readings_just_under_the_line_cannot_lift_it_past_the_cap():
    feed = Feed(models(calibration="quantile", max_z=5.0))
    feed.calm(600, noise=0.01)

    for i in range(3000):  # trusted, plausible, a hair under what is surprising, always the same side
        feed.send(0.30 + (feed.models.threshold("wl-01-01", "level_m") - 0.1) * 0.03 * (-1 if i % 2 else 1))

    assert 4.0 <= feed.models.threshold("wl-01-01", "level_m") <= 5.0


def test_a_distrusted_reading_does_not_feed_the_calibration():
    feed = Feed(models(calibration="quantile"))
    feed.calm(600, noise=0.01)
    before = feed.models.threshold("wl-01-01", "level_m")

    for i in range(2000):
        feed.send(0.30 + 0.1 * (-1) ** i, trusted=False)

    assert feed.models.threshold("wl-01-01", "level_m") == before


def test_an_accepted_step_starts_the_calibration_again():
    feed, _ = heavy_feed(models(calibration="quantile"))
    assert feed.models.threshold("wl-01-01", "level_m") > 4.1

    for _ in range(3):
        feed.send(2.0)

    assert feed.models.threshold("wl-01-01", "level_m") == 4.0  # a new normal, too little history again


def test_a_deviation_of_the_cap_or_more_is_always_reported_however_the_threshold_was_walked():
    from brain.mind.forward_bench import STREAMS, run

    reported = run(ForwardPolicy(calibration="quantile"), STREAMS["walk"](1000))

    assert 500 in reported  # the 6-spread spike after the walk


# --- a remembered previous normal ------------------------------------------------------------------------------------


def flood_then_back(models_):
    feed = Feed(models_)
    feed.calm(30)
    up = [feed.send(1.10)[1] for _ in range(3)]  # a flood: the third reading is accepted as the new normal
    feed.calm(20, level=1.10)
    return feed, up


def test_without_recovery_a_return_to_the_old_level_is_a_doubted_surprise():
    feed, _ = flood_then_back(models(recover=False))

    _, found = feed.send(0.30)

    assert found and found[0].doubted and not found[0].recovered


def test_with_recovery_a_return_to_the_old_level_is_recognised_at_once():
    feed, up = flood_then_back(models(recover=True))
    assert up[2][0].rebaselined

    reading, found = feed.send(0.30)

    (surprise,) = found
    assert surprise.recovered and not surprise.doubted and not surprise.rebaselined
    assert not feed.models.is_doubted(reading.reading_id)
    assert feed.send(0.31)[1] == []  # the old normal is the baseline again
    assert abs(feed.models.baseline("wl-01-01", "level_m")[0] - 0.30) < 0.03


def test_a_level_near_neither_normal_is_an_ordinary_doubted_surprise():
    feed, _ = flood_then_back(models(recover=True))

    _, found = feed.send(0.70)

    assert found and found[0].doubted and not found[0].recovered


def test_the_old_normal_is_forgotten_after_the_calibration_window():
    feed, _ = flood_then_back(models(recover=True, calibration_window=100))
    feed.calm(150, level=1.10)

    _, found = feed.send(0.30)

    assert found and found[0].doubted and not found[0].recovered


def test_a_distrusted_reading_never_recovers_a_baseline():
    feed, _ = flood_then_back(models(recover=True))

    _, found = feed.send(0.30, trusted=False)

    assert found and not found[0].recovered
    assert abs(feed.models.baseline("wl-01-01", "level_m")[0] - 1.10) < 0.05


def test_the_flood_level_is_remembered_too_so_a_flapping_sensor_is_not_doubted_each_time():
    feed, _ = flood_then_back(models(recover=True))
    assert feed.send(0.30)[1][0].recovered

    _, found = feed.send(1.10)

    assert found and found[0].recovered and not found[0].doubted
