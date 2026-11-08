"""The tunable surface: the only parameters the Brain may change about itself, and how a tuned overlay is applied."""

import pytest

from brain.config import BrainConfig, PartnersConfig, Policy
from brain.mind.surface import EXCLUDED_SECTIONS, SURFACE, SurfaceError, apply_overlay, load_overlay, save_overlay
from brain.scenario import load_scenario
from tests.test_scenarios import play


def value_at(policy: Policy, path: str):
    node = policy
    for part in path.split("."):
        node = node[part] if isinstance(node, dict) else getattr(node, part)
    return node


@pytest.mark.parametrize("path", sorted(SURFACE))
def test_every_surface_parameter_exists_and_its_default_lies_inside_its_own_range_on_a_step(path):
    tunable = SURFACE[path]
    default = value_at(Policy(), path)

    assert tunable.low <= default <= tunable.high
    assert abs((default - tunable.low) / tunable.step - round((default - tunable.low) / tunable.step)) < 1e-9
    assert abs((tunable.high - tunable.low) / tunable.step - round((tunable.high - tunable.low) / tunable.step)) < 1e-9


def test_nothing_outside_the_surface_can_be_proposed():
    for path in ("gate.max_actions_per_incident", "gate.impact", "tactics.reserve_units", "scoring.suspect_threshold",
                 "triage.min_confidence", "learning.min_support", "forward.adopt_after", "forward.warmup", "workspace.slots",
                 "workspace.corroboration_by", "workspace.team_types", "forward.coupled", "forward.effects", "workspace.severity"):
        with pytest.raises(SurfaceError):
            apply_overlay(Policy(), {path: 1})


def test_the_sections_that_are_never_reachable_are_the_ones_that_matter_for_safety():
    assert {"gate", "tactics", "scoring", "triage", "learning"} <= set(EXCLUDED_SECTIONS)
    assert not {path.split(".")[0] for path in SURFACE} & set(EXCLUDED_SECTIONS)


def test_an_overlay_sets_values_and_leaves_the_rest_alone():
    tuned = apply_overlay(Policy(), {"forward.z_threshold": 4.5, "workspace.weights.severity": 3.5})

    assert tuned.forward.z_threshold == 4.5 and tuned.workspace.weights["severity"] == 3.5
    assert tuned.workspace.weights["trust"] == Policy().workspace.weights["trust"]
    assert tuned.forward.alpha == Policy().forward.alpha and tuned.gate == Policy().gate


def test_an_empty_overlay_changes_nothing():
    assert apply_overlay(Policy(), {}) == Policy()


@pytest.mark.parametrize("path, value", [("forward.z_threshold", 3.0), ("forward.z_threshold", 9.0), ("workspace.ignite_at", 0.1),
                                         ("workspace.margin", "wide"), ("forward.z_threshold", True)])
def test_a_value_outside_its_range_or_of_the_wrong_kind_is_refused(path, value):
    with pytest.raises(SurfaceError):
        apply_overlay(Policy(), {path: value})


def test_an_overlay_can_be_saved_and_read_back_with_its_note(tmp_path):
    save_overlay(tmp_path, {"forward.z_threshold": 4.25}, "tuned on 26 October")

    overlay, problem = load_overlay(tmp_path)

    assert overlay == {"forward.z_threshold": 4.25} and problem is None


def test_a_folder_without_an_overlay_is_an_untuned_brain():
    assert load_overlay(None) == ({}, None)


def test_a_corrupt_overlay_is_ignored_and_the_problem_is_reported(tmp_path):
    (tmp_path / "overlay.yaml").write_text("overlay: [not, a, mapping]\n")

    overlay, problem = load_overlay(tmp_path)

    assert overlay == {} and "overlay" in problem


def test_an_overlay_with_a_path_off_the_surface_is_ignored_whole(tmp_path):
    (tmp_path / "overlay.yaml").write_text("overlay: {forward.z_threshold: 4.5, gate.max_actions_per_incident: 99}\n")

    overlay, problem = load_overlay(tmp_path)

    assert overlay == {} and "gate.max_actions_per_incident" in problem


async def test_the_brain_loads_the_overlay_at_start_and_says_so(tmp_path):
    save_overlay(tmp_path, {"forward.z_threshold": 4.5}, "a test")
    held = {}

    result = await play(load_scenario("d3"), partners=PartnersConfig(brain=BrainConfig(tuned_dir=str(tmp_path))),
                        on_service=lambda service: held.update(service=service))

    assert held["service"].policy.forward.z_threshold == 4.5
    started = result.sink.of("brain.started")[0].data
    assert started["tuned"] == {"forward.z_threshold": 4.5} and started["tuned_problem"] is None


async def test_a_brain_without_an_overlay_is_untuned_and_says_so():
    result = await play(load_scenario("d3"))

    started = result.sink.of("brain.started")[0].data
    assert started["tuned"] == {} and started["tuned_problem"] is None
