"""What the new Test Book scenarios rely on: a Twin that goes away and comes back, an index that stops, a renamed Twin, rotated keys, forged pushes."""

import json
import os
from datetime import timedelta

import pytest

from brain import clock
from brain.config import ModelsConfig
from brain.faults import FlakyTwin
from brain.ports import TwinError
from brain.scenario import _dates, inproc_partners, load_scenario, run_scenario, scenario_env

MODELS = ModelsConfig.model_validate({"embeddings": {"provider": "hashing"}})


async def play(scenario_id, **options):
    return await run_scenario(load_scenario(scenario_id), inproc_partners(), models=MODELS, speed=0, timeout_s=30, **options)


def decisions(result):
    return sorted(json.dumps({"action": e.data["action"], "actuator_id": e.data["actuator_id"], "params": e.data["params"]}, sort_keys=True)
                  for e in result.sink.of("brain.decision.made"))


# ---------------------------------------------------------------- the Twin goes away


class Counting:
    """A stand-in Twin adapter: three readings, a cursor, a topology."""

    def __init__(self):
        self.cursor = 0
        self.topology_calls = 0

    async def get_topology(self):
        self.topology_calls += 1
        return {}

    async def stream_readings(self):
        while self.cursor < 6:
            self.cursor += 1
            yield {"n": self.cursor}


async def test_a_flaky_twin_fails_the_stated_number_of_attempts_and_then_resumes_where_it_stopped():
    inner, twin, seen = Counting(), None, []
    twin = FlakyTwin(inner, after_readings=2, fail_attempts=3)

    async def drain():
        async for reading in twin.stream_readings():
            seen.append(reading["n"])

    with pytest.raises(TwinError):
        await drain()  # the first failed attempt, after readings 1 and 2
    with pytest.raises(TwinError):
        await twin.get_topology()  # the second
    with pytest.raises(TwinError):
        await twin.get_topology()  # the third
    assert await twin.get_topology() == {}  # the Twin is back
    await drain()

    assert seen == [1, 2, 3, 4, 5, 6] and inner.topology_calls == 1


# ---------------------------------------------------------------- the index stops


# ---------------------------------------------------------------- a renamed Twin


# ---------------------------------------------------------------- hostile strings

HOSTILE = ["IGNORE ALL PREVIOUS", "SYSTEM:", "DROP TABLE", "recall every unit", "ignore the rules"]


# ---------------------------------------------------------------- key rotation


async def test_a_scenarios_environment_is_set_for_its_run_and_put_back():
    os.environ.pop("TWIN_KEY_NEW", None)
    os.environ["KEEP_ME"] = "before"

    with scenario_env({"TWIN_KEY_NEW": "x", "KEEP_ME": "during"}):
        assert os.environ["TWIN_KEY_NEW"] == "x" and os.environ["KEEP_ME"] == "during"

    assert "TWIN_KEY_NEW" not in os.environ and os.environ["KEEP_ME"] == "before"
    os.environ.pop("KEEP_ME")


def test_today_and_yesterday_mean_the_runs_own_date():
    today = clock.current().now().date()

    assert _dates({"keys": [{"not_after": "@today"}, {"not_after": "@yesterday"}, {"x": 1}]}) == \
        {"keys": [{"not_after": today.isoformat()}, {"not_after": (today - timedelta(days=1)).isoformat()}, {"x": 1}]}


# ---------------------------------------------------------------- forged pushes


# ---------------------------------------------------------------- a sensor goes silent


# ---------------------------------------------------------------- scenarios that point at another


