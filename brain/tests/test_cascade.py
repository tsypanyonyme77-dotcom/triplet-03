"""What goes dark when a zone is cut, and which single loss is worst."""

import pytest

from brain.citygraph import MemoryGraphStore
from brain.engines.cascade import cascade, load_dependencies, n_minus_1

TOPOLOGY = {
    "zones": [{"id": z} for z in ("z1", "z2", "z3")], "adjacency": [["z1", "z2"], ["z2", "z3"]],
    "facilities": [{"id": "hosp-1", "type": "hospital", "zone_id": "z1"}, {"id": "sig-2", "type": "signal_controller", "zone_id": "z2"},
                   {"id": "valve-3", "type": "valve", "zone_id": "z3"}, {"id": "ps-3", "type": "depot", "zone_id": "z3"}],
}


def city():
    store = MemoryGraphStore()
    store.load_topology(TOPOLOGY)
    return store


def test_cascade_marks_every_facility_in_a_cut_zone_dark():
    impact = cascade(city(), {}, {"z3"})

    assert impact.dark == ["ps-3", "valve-3"] and impact.weight == 4.0 and impact.by_kind == {"depot": 1, "valve": 1}


def test_a_facility_that_depends_on_a_dark_one_goes_dark_too():
    impact = cascade(city(), {"sig-2": ["valve-3"]}, {"z3"})

    assert impact.dark == ["ps-3", "sig-2", "valve-3"]


def test_n_minus_1_ranks_the_zone_with_the_hospital_highest():
    ranked = n_minus_1(city(), {})

    assert ranked[0][0] == "z1" and ranked[0][1].weight == 10.0 and [z for z, _ in ranked] == ["z1", "z3", "z2"]


def test_a_dependency_the_topology_does_not_know_is_rejected(tmp_path):
    path = tmp_path / "deps.yaml"
    path.write_text("depends_on:\n  sig-2: [grid-99]\n")

    with pytest.raises(ValueError, match="grid-99"):
        load_dependencies(city(), path)


def test_the_shipped_dependency_file_names_only_things_the_small_city_has():
    import json
    from pathlib import Path

    store = MemoryGraphStore()
    store.load_topology(json.loads((Path(__file__).parents[1] / "scenarios/topology/small-city.json").read_text()))

    assert load_dependencies(store) == {"sig-05-01": ["grid-04"]}
