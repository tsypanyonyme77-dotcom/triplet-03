"""The forward-model benchmark: synthetic sensor streams with a known truth, and what a configuration makes of them."""

import math

from brain.config import ForwardPolicy
from brain.mind.forward_bench import CHANGE_AT, SPREAD, STREAMS, score, table


def test_the_same_seed_gives_the_same_stream():
    for name, stream in STREAMS.items():
        assert stream(7) == stream(7), name
        assert stream(7) != stream(8), name


def test_every_stream_has_a_thousand_readings():
    assert all(len(stream(1)) == 1000 for stream in STREAMS.values())


def test_a_calm_stream_has_no_change_and_a_step_has_the_stated_size():
    calm, big = STREAMS["calm"](3), STREAMS["step_l"](3)

    before = sum(big[:CHANGE_AT]) / CHANGE_AT
    after = sum(big[CHANGE_AT + 50:]) / len(big[CHANGE_AT + 50:])
    assert abs(sum(calm[:500]) / 500 - sum(calm[500:]) / 500) < 0.01
    assert abs((after - before) / SPREAD - 20) < 1.0


def test_a_spike_is_one_reading_twenty_spreads_out():
    values = STREAMS["spike"](3)

    far = [i for i, v in enumerate(values) if abs(v - 0.30) > 10 * SPREAD]

    assert far == [CHANGE_AT]


def test_the_ramp_climbs_eight_spreads_and_stays():
    values = STREAMS["ramp"](3)

    assert abs((sum(values[-50:]) / 50 - sum(values[:CHANGE_AT]) / CHANGE_AT) / SPREAD - 8) < 1.0


def test_the_default_policy_adopts_no_spike_and_catches_a_big_step():
    scores = score(ForwardPolicy(), range(0, 3))

    assert scores["spike"]["spike_adopted"] == 0
    assert scores["step_l"]["delay"] is not None and math.isfinite(scores["step_l"]["delay"])
    assert scores["step_back"]["delay"] is not None


def test_a_calm_gaussian_stream_raises_next_to_no_false_doubts():
    scores = score(ForwardPolicy(), range(0, 3))

    assert scores["calm"]["false_doubts_per_1000"] < 1.0


def test_the_table_lists_every_stream():
    text = table(score(ForwardPolicy(), range(0, 2)))

    assert all(name in text for name in STREAMS)


def test_injected_anomalies_are_where_they_are_said_to_be():
    from brain.mind.forward_bench import ANOMALY_AT, ANOMALY_SIZES, anomaly_stream

    values = anomaly_stream(6.0, 5)

    far = [i for i, v in enumerate(values) if abs(v - 0.30) > 3 * SPREAD]
    assert far == list(ANOMALY_AT) and ANOMALY_SIZES == (4.5, 6.0, 10.0)


def test_the_default_policy_reports_nearly_every_injected_anomaly_and_a_noisy_small_one_can_slip_under_the_line():
    from brain.mind.forward_bench import recall

    default = recall(ForwardPolicy(), range(0, 3))

    assert 0.95 <= default <= 1.0 and default > recall(ForwardPolicy(z_threshold=5.5), range(0, 3))


def test_a_policy_that_is_too_deaf_misses_the_small_anomalies():
    from brain.mind.forward_bench import recall

    deaf = recall(ForwardPolicy(z_threshold=5.5), range(0, 3))

    assert 0.5 < deaf < 1.0
