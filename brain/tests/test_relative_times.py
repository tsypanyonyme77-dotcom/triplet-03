"""With `team.relative_times` on, an agent's brief never carries a calendar time, so a rerun sees the same prompt."""

import json
import re

from brain.config import ModelsConfig
from brain.repro import decisions_of, run_briefs, run_events

ON = ModelsConfig.model_validate({"embeddings": {"provider": "hashing"}, "team": {"relative_times": True}})
OFF = ModelsConfig.model_validate({"embeddings": {"provider": "hashing"}})


def test_the_switch_is_off_by_default():
    assert ModelsConfig().team.relative_times is False


async def test_with_relative_times_a_brief_has_no_calendar_time():
    briefs = await run_briefs("t14", models=ON)

    for role, brief in briefs.items():
        assert not re.search(r"\d{4}-\d\d-\d\dT", json.dumps(brief)), role
    assert isinstance(briefs["analyst"]["incident"]["seconds_since_incident"], int)
    assert "occurred_at" not in briefs["analyst"]["incident"]


async def test_with_the_switch_off_a_brief_keeps_the_calendar_time():
    briefs = await run_briefs("t14", models=OFF)

    assert "occurred_at" in briefs["analyst"]["incident"]


async def test_the_scripted_team_decides_the_same_with_the_switch_on_or_off():
    on, off = await run_events("t14", models=ON), await run_events("t14", models=OFF)

    assert decisions_of(on) == decisions_of(off)
