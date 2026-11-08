"""Coupled sensors: two gauges that should move together. One that drifts alone is disputed, however slowly it drifts."""

import random
from datetime import timedelta

from brain.config import ForwardPolicy
from brain.contracts import CONTRACT_VERSION, VALUE_MODELS, SensorReading
from brain.mind.forward import ForwardModels
from brain.mind.neighbours import NeighbourModels
from tests.conftest import T0

GROUP = [["wl-01-01", "wl-02-01"]]


class Pair:
    """Two harbour gauges in adjacent zones, read once a second, one after the other."""

    def __init__(self, **policy):
        self.policy = ForwardPolicy(coupled=GROUP, **policy)
        self.forward = ForwardModels(self.policy)
        self.neighbours = NeighbourModels(self.policy, self.forward)
        self.seq = {"wl-01-01": 0, "wl-02-01": 0}
        self.clock = 0
        self.rng = random.Random(4)

    def send(self, sensor, level, trusted=True, seconds=None):
        self.seq[sensor] += 1
        self.clock = self.clock + 1 if seconds is None else seconds
        value = {"level_m": level}
        reading = SensorReading(contract_version=CONTRACT_VERSION, sensor_id=sensor, type="water_level",
                                zone_id="zone-01" if sensor == "wl-01-01" else "zone-02",
                                timestamp=T0 + timedelta(seconds=self.clock), sequence_no=self.seq[sensor], value=value)
        parsed = VALUE_MODELS["water_level"].model_validate(value)
        own = self.forward.observe(reading, parsed, trusted)
        found = self.neighbours.observe(reading, parsed, trusted)
        return reading, own, found

    def both(self, a, b, trusted=True):
        first = self.send("wl-01-01", a, trusted)
        second = self.send("wl-02-01", b, trusted)
        return first, second

    def calm(self, count, level=0.30, noise=0.01):
        return [self.both(round(level + self.rng.gauss(0, noise), 4), round(level + self.rng.gauss(0, noise), 4)) for _ in range(count)]


def test_two_coupled_sensors_that_rise_together_raise_no_dispute():
    pair = Pair()
    pair.calm(40)

    results = []
    for step in range(60):
        level = 0.30 + step * 0.02
        results.append(pair.both(level + pair.rng.gauss(0, 0.01), level + pair.rng.gauss(0, 0.01)))

    assert all(not first[2] and not second[2] for first, second in results)


def test_a_sensor_that_drifts_alone_is_disputed_and_stays_disputed_while_it_drifts():
    pair = Pair()
    pair.calm(40)

    disputed = []
    for step in range(80):
        first, second = pair.both(0.30 + step * 0.02 + pair.rng.gauss(0, 0.01), 0.30 + pair.rng.gauss(0, 0.01))
        disputed.append(pair.forward.is_doubted(first[0].reading_id))

    assert not any(disputed[:4])  # the first few steps are inside the noise
    assert all(disputed[12:])  # then every reading of the drifting sensor is disputed, not only the first
    assert first[2] and first[2][0].kind == "neighbour" and first[2][0].neighbour == "wl-02-01" and first[2][0].doubted


def test_the_dispute_ends_when_the_two_agree_again():
    pair = Pair()
    pair.calm(40)
    for step in range(40):
        pair.both(0.30 + step * 0.03, 0.30)

    pair.both(0.30, 0.30)
    reading, own, found = pair.send("wl-01-01", 0.30)

    assert found == [] and not pair.forward.is_doubted(reading.reading_id)


def test_a_slow_drift_is_not_followed_by_the_difference_baseline():
    pair = Pair()
    pair.calm(40)

    for step in range(600):  # a very slow creep: 0.003 m a second, a tenth of a spread
        pair.both(0.30 + step * 0.003, 0.30)

    reading, own, found = pair.send("wl-01-01", 0.30 + 600 * 0.003)
    assert found, "an 1.8 m creep over ten minutes must still be disputed"


def test_a_sensor_outside_every_coupled_group_is_never_compared():
    pair = Pair()
    pair.calm(40)
    pair.seq["wl-03-01"] = 0

    other = SensorReading(contract_version=CONTRACT_VERSION, sensor_id="wl-03-01", type="water_level", zone_id="zone-03",
                          timestamp=T0 + timedelta(seconds=100), sequence_no=1, value={"level_m": 5.0})

    assert pair.neighbours.observe(other, VALUE_MODELS["water_level"].model_validate({"level_m": 5.0}), True) == []


def test_a_distrusted_reading_neither_feeds_nor_is_compared():
    pair = Pair()
    pair.calm(40)

    results = [pair.send("wl-01-01", 5.0 + i, trusted=False)[2] for i in range(30)]

    assert all(r == [] for r in results)
    assert pair.send("wl-01-01", 0.30)[2] == []  # the baseline of the pair never saw the distrusted values


def test_a_partner_reading_older_than_the_window_is_not_compared():
    pair = Pair(coupled_window_s=10)
    pair.calm(40)
    pair.send("wl-02-01", 0.30)

    _, _, found = pair.send("wl-01-01", 3.0, seconds=pair.clock + 600)

    assert found == []


def test_the_two_do_not_dispute_before_the_pair_has_enough_history():
    pair = Pair()

    first, second = pair.both(0.30, 3.0)

    assert not first[2] and not second[2]


def test_retracting_a_disputed_reading_removes_it_from_the_dispute():
    pair = Pair()
    pair.calm(40)
    for step in range(30):
        pair.both(0.30 + step * 0.03, 0.30)
    reading = pair.send("wl-01-01", 1.5)[0]
    assert pair.forward.is_doubted(reading.reading_id)

    pair.forward.forget(reading.reading_id)

    assert not pair.forward.is_doubted(reading.reading_id)
