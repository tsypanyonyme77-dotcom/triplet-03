"""Pedestrians never turn on the spot (tools/ped_turning.py): the viewer turns the model
to the recorded heading, so a heading swinging while the body stands still is a figure
spinning on screen."""
import pytest

from twin.world import scenarios
from tools.ped_turning import measure


@pytest.mark.parametrize("name", list(scenarios.SCENARIOS))
def test_no_pedestrian_turns_on_the_spot(name):
    result = measure(name, 180.0)
    assert result["spin_windows"] == 0, result
