"""Load shedding: remove at least the excess, at the least impact, exactly (checked against brute force)."""

import itertools

from brain.engines.shed import shed

LOADS = {"z1": 400.0, "z2": 300.0, "z3": 250.0, "z4": 120.0}
IMPACT = {"z1": 10.0, "z2": 1.0, "z3": 2.0, "z4": 1.0}  # z1 has the hospital


def brute(loads, capacity, ratio, impact):
    excess = sum(loads.values()) - ratio * capacity
    best = None
    for r in range(len(loads) + 1):
        for combo in itertools.combinations(sorted(loads), r):
            if sum(loads[z] for z in combo) >= excess:
                cost = sum(impact[z] for z in combo)
                best = cost if best is None or cost < best else best
    return best


def test_shedding_removes_enough_load_with_the_least_impact_matching_brute_force():
    result = shed(LOADS, 900.0, 0.8, IMPACT)  # 1070 kW against a 720 kW target: 350 kW to lose

    assert result.load_removed_kw >= result.excess_kw == 350.0
    assert result.impact == brute(LOADS, 900.0, 0.8, IMPACT) and result.certificate.status == "optimal"


def test_shedding_never_picks_a_zone_whose_cut_would_darken_a_hospital_if_another_set_suffices():
    assert "z1" not in shed(LOADS, 900.0, 0.8, IMPACT).disconnect


def test_a_hospital_zone_is_chosen_only_when_nothing_else_will_do():
    assert "z1" in shed({"z1": 400.0, "z2": 100.0}, 300.0, 0.8, {"z1": 10.0, "z2": 1.0}).disconnect


def test_nothing_is_shed_when_the_grid_is_under_the_target():
    result = shed(LOADS, 2000.0, 0.8, IMPACT)

    assert result.disconnect == [] and result.certificate.status == "optimal"


def test_the_same_loads_give_the_same_choice_every_time():
    assert len({tuple(shed(LOADS, 900.0, 0.8, IMPACT).disconnect) for _ in range(5)}) == 1
