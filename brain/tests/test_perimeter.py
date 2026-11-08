"""The perimeter solver: the fewest units that seal the suspect in, each reaching its zone first, and how likely that is to hold."""

import json
from pathlib import Path

import networkx as nx

from brain.citygraph import MemoryGraphStore
from brain.engines.perimeter import perimeter
from brain.engines.robust import robust

SMALL = Path(__file__).parents[1] / "scenarios/topology/small-city.json"


def small_city() -> MemoryGraphStore:
    store = MemoryGraphStore()
    store.load_topology(json.loads(SMALL.read_text()))
    return store


def line(stations) -> MemoryGraphStore:
    """z1 - z2 - z3 - z4 - z5, the exit at z5."""
    store = MemoryGraphStore()
    store.load_topology({"zones": [{"id": f"z{n}"} for n in range(1, 6)], "adjacency": [[f"z{n}", f"z{n + 1}"] for n in range(1, 5)], "exits": ["z5"], "facilities": stations})
    return store


def station(id_, zone, units=1):
    return {"id": id_, "type": "police_station", "zone_id": zone, "actuator_id": f"d-{id_}", "units": units}


def paths_to_exits_through_held(store, suspect, held):
    graph = store.zones.copy()
    graph.remove_nodes_from(held)
    return [e for e in store.exits if suspect in graph and e in graph and nx.has_path(graph, suspect, e)]


def test_the_perimeter_cuts_every_path_to_an_exit_on_the_small_city():
    store = small_city()
    plan = perimeter(store, "zone-07")

    assert plan.feasible and plan.zones and paths_to_exits_through_held(store, "zone-07", plan.zones) == []


def test_the_solver_uses_the_minimum_number_of_units_on_a_hand_case():
    store = line([station("A", "z3"), station("B", "z4", 2)])
    plan = perimeter(store, "z1")

    assert plan.units_used == 1 and plan.zones[0] in ("z2", "z3", "z4", "z5")  # one zone anywhere on the line is a cut


def test_a_zone_the_units_cannot_reach_in_time_is_not_held():
    store = line([station("A", "z5")])  # the only station is at the exit end, far from a suspect at z1
    plan = perimeter(store, "z1", unit_hop_s=60.0, suspect_hop_s=60.0)

    assert plan.zones == ["z5"] or plan.zones == ["z4"] or all(plan.arrival_slack_s[z] >= 0 for z in plan.zones)
    assert all(slack >= 0 for slack in plan.arrival_slack_s.values())


def test_when_no_perimeter_is_possible_the_solver_says_infeasible_and_names_the_nearest_miss():
    store = line([station("A", "z1")])
    plan = perimeter(store, "z4", unit_hop_s=120.0, suspect_hop_s=30.0)  # the suspect is next to the exit and the unit is four slow hops away

    assert not plan.feasible and plan.certificate.status == "infeasible" and "nearest miss" in plan.reason


def test_a_suspect_already_at_an_exit_cannot_be_sealed_in():
    assert not perimeter(line([station("A", "z3")]), "z5").feasible


def test_robust_probability_falls_as_noise_rises():
    plan = perimeter(line([station("A", "z2"), station("B", "z3")]), "z1", unit_hop_s=60.0, suspect_hop_s=90.0)
    calm, rough = robust(plan, sigma=0.05), robust(plan, sigma=0.8)

    assert plan.feasible and calm > rough and calm >= 0.9


def test_the_same_plan_and_seed_give_the_same_probability():
    plan = perimeter(line([station("A", "z2")]), "z1")

    assert robust(plan, sigma=0.4, seed=7) == robust(plan, sigma=0.4, seed=7)


def test_the_solver_never_beats_the_unit_count_of_the_minimum_cut():
    store = small_city()
    plan = perimeter(store, "zone-07", unit_hop_s=1.0, suspect_hop_s=1000.0)  # time never binds, so it must equal the plain minimum cut
    from brain.tools.geo import containment_cut

    assert plan.units_used == len(containment_cut(store, "zone-07")["zones"])


def test_a_team_plan_with_more_units_than_the_optimum_is_recorded_with_its_gap_and_late_zones_are_named():
    from brain.engines.perimeter import check_plan

    store = small_city()
    agreeing = check_plan(store, "zone-07", ["zone-04", "zone-08"])
    wasteful = check_plan(store, "zone-07", ["zone-04", "zone-08", "zone-05"])
    stale = check_plan(store, "zone-08", ["zone-04", "zone-08"])  # the suspect has already reached one of the held zones

    assert agreeing["solver_gap"] == 0 and agreeing["team_zones_late"] == [] and wasteful["solver_gap"] == 1
    assert stale["team_zones_late"] == ["zone-08"] and stale["solver_gap"] == -1
