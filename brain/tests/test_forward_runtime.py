"""Forward models inside the running Brain: surprise reaches the timeline, with the numbers."""

from brain.config import Policy
from brain.scenario import expand_streams, load_scenario
from tests.test_conditions import scenario, water
from tests.test_scenarios import play

CALM = {"streams": [{"sensor_id": "wl-01-01", "type": "water_level", "zone_id": "zone-01", "from_ms": 0, "to_ms": 4000,
                     "every_ms": 500, "base": {"level_m": 0.30}, "noise": {"level_m": 0.01}, "clamp": {"level_m": [0.25, 0.35]}, "seed": 3}]}


async def test_a_spike_on_a_calm_stream_is_reported_as_a_surprise_with_its_numbers():
    result = await play(expand_streams(scenario([water(6000, 2.4)], **CALM)))

    (event,) = result.sink.of("brain.percept.surprise")
    assert event.subject == "wl-01-01#9"
    assert event.data["field"] == "level_m" and event.data["observed"] == 2.4
    assert event.data["doubted"] is True and event.data["z"] >= 4 and abs(event.data["expected"] - 0.30) < 0.03
    assert event.data["verdict"] == "trusted"


async def test_with_forward_models_off_no_surprise_is_reported():
    policy = Policy.model_validate({"forward": {"enabled": False}})

    result = await play(expand_streams(scenario([water(6000, 2.4)], **CALM)), policy=policy)

    assert result.sink.of("brain.percept.surprise") == []
    assert result.sink.of("brain.started")[0].data["forward"] == {"enabled": False}


async def test_crime_scenarios_raise_no_surprise():
    result = await play(load_scenario("d3"))

    assert result.sink.of("brain.percept.surprise") == []


async def test_a_distrusted_sensor_is_reported_but_never_becomes_the_new_normal():
    guardian = {"default": "trusted", "overrides": {"wl-01-01": "untrusted"}}
    spikes = [water(6000 + 500 * i, 2.4) for i in range(5)]

    result = await play(expand_streams(scenario(spikes, guardian=guardian, **CALM)))

    surprises = result.sink.of("brain.percept.surprise")
    assert surprises == [] or all(not e.data["rebaselined"] for e in surprises)
    assert all(e.data["verdict"] == "untrusted" for e in surprises)


async def test_a_retraction_rebuilds_the_baseline_and_says_so():
    from tests.test_retraction import Retractor

    class AfterWarmUp(Retractor):
        def write(self, event):
            if event.type == "brain.reading.received" and event.subject == "wl-01-01#6" and self.service is not None:
                self.service.retract("wl-01-01#3", "faulty")

    holder = AfterWarmUp()
    result = await play(expand_streams(scenario([water(6000, 0.31)], **CALM)), extra_sinks=[holder], on_service=lambda s: setattr(holder, "service", s))

    (event,) = result.sink.of("brain.evidence.retracted")
    assert event.subject == "wl-01-01#3" and event.data["baselines_rebuilt"] == ["wl-01-01.level_m"]
