"""The department agents are on in everything you run, and off only where the frozen baselines need the plain pipeline."""

from brain.cli import build_parser
from brain.commands.common import _models
from brain.config import ModelsConfig


def models_for(*argv):
    return _models(build_parser().parse_args(list(argv)))


def test_scenario_serve_and_run_turn_the_department_desks_on_by_default():
    for argv in (["scenario", "b13"], ["serve"], ["run"]):
        assert models_for(*argv).team.departments == "on", argv


def test_no_departments_turns_them_off_and_departments_turns_them_on_again():
    assert models_for("scenario", "b13", "--no-departments").team.departments == "off"
    assert models_for("scenario", "b13", "--no-departments", "--departments").team.departments == "on"


def test_the_library_default_stays_off_so_the_baselines_measure_the_plain_pipeline():
    assert ModelsConfig().team.departments == "off"
