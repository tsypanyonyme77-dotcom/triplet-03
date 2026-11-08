"""The standing reproducibility check: no scenario may show a varying field once id, time and timing are removed."""

import asyncio

import pytest

from brain.repro import census, run_events

SCENARIOS = ["d1", "d2", "d3", "d4"]

# Fields that come from the partner's own clock, so they vary whenever the partner's clock does. The Brain does not make them.
PARTNER_CLOCK = {"brain.action.result.data.reverts_at"}  # the Twin's signal-phase answer: when the phase reverts, on its clock


@pytest.mark.parametrize("scenario_id", SCENARIOS)
def test_a_deterministic_run_has_no_varying_field(scenario_id):
    runs = [asyncio.run(run_events(scenario_id, deterministic=True)) for _ in range(2)]

    assert census(runs) == [], f"{scenario_id}: {[(f.path, f.values) for f in census(runs)]}"


@pytest.mark.parametrize("scenario_id", ["d3", "d4"])
def test_a_live_run_varies_only_in_what_the_partner_clock_makes(scenario_id):
    runs = [asyncio.run(run_events(scenario_id)) for _ in range(2)]

    assert [f.path for f in census(runs) if f.path not in PARTNER_CLOCK] == []


def test_the_event_order_of_a_deterministic_run_does_not_depend_on_the_scheduler():
    """b5 swapped `decision.made` and `deliberation.finished` in about one run in three, because the team ran while the reflex path awaited the Twin."""
    runs = [asyncio.run(run_events("d2", deterministic=True)) for _ in range(10)]

    assert census(runs) == []
    assert len({tuple(e["type"] for e in run) for run in runs}) == 1
