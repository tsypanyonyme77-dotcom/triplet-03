"""The decision model: the student reflects what its teacher taught, and the decider plugs into the sim."""
from __future__ import annotations

import random
from statistics import mean

import pytest

from twin.engine.decision import Decider
from twin.engine.decision.profile import make_profile
from twin.engine.decision.schema import CATEGORIES, FAR, TRAITS, feature_names, is_open
from twin.engine.decision.situation import clock_hour, map_scale
from twin.engine.decision.student import Student
from twin.world import scenarios


@pytest.fixture(scope="module")
def student() -> Student:
    return Student.load()


def situation(rng: random.Random, hour: int = 12, cats=None, **cand_over) -> dict:
    """A random person with 12 candidate places at similar distances, no events."""
    cats = cats or [rng.choice([c for c in CATEGORIES if c != "home"]) for _ in range(12)]
    cands = [{"cat": c, "dist": 400, "open": is_open(c, hour), "is_home": False, "is_anchor": False,
              "crowd": 0.5, "d_fire": FAR, "d_crash": FAR, "d_closed": FAR, **cand_over} for c in cats]
    return {"traits": {t: round(rng.random(), 2) for t in TRAITS}, "role": rng.choice(["worker", "retiree"]),
            "kind": "pedestrian", "hour": hour, "current": "cafe", "cand": cands,
            "agent_event_dist": FAR, "witnessed": False}


def test_model_and_schema_agree_on_the_features(student):
    assert student.model_features == feature_names()


def test_the_student_avoids_closed_places(student):
    rng = random.Random(1)
    closed_share, uniform = [], []
    for _ in range(150):
        s = situation(rng, hour=3)   # at night most places are closed
        p = student.scores(s)
        shut = [not c["open"] for c in s["cand"]]
        closed_share.append(sum(x for x, c in zip(p, shut) if c) / sum(p))
        uniform.append(sum(shut) / len(shut))
    assert mean(closed_share) < 0.5 * mean(uniform)


def test_the_student_avoids_places_near_a_fire(student):
    rng = random.Random(2)
    with_fire, without = [], []
    for _ in range(150):
        s = situation(rng)
        base = student.scores(s)[0]
        s["cand"][0]["d_fire"] = 60.0
        with_fire.append(student.scores(s)[0])
        without.append(base)
    assert mean(with_fire) < 0.7 * mean(without)


def test_a_distant_place_is_less_attractive_than_a_near_one(student):
    rng = random.Random(3)
    near, far = [], []
    for _ in range(150):
        s = situation(rng)
        s["cand"][0]["dist"] = 100
        near.append(student.scores(s)[0])
        s["cand"][0]["dist"] = 2000
        far.append(student.scores(s)[0])
    assert mean(far) < mean(near)


def test_profiles_are_repeatable_and_belong_to_the_person():
    sim = scenarios.build("city", 1).sim
    a, b = make_profile("ped3", sim.places, 1), make_profile("ped3", sim.places, 1)
    assert a == b and a != make_profile("ped4", sim.places, 1)
    assert next(p for p in sim.places if p["id"] == a.home_id)["category"] == "home"


def test_the_clock_wraps_a_day():
    assert clock_hour(0) == 8 and clock_hour(60) == 9 and clock_hour(60 * 16) == 0


def test_the_map_scale_puts_the_median_distance_at_the_training_median():
    sim = scenarios.build("city", 1).sim
    assert 3 < map_scale(sim.places) < 12   # the two-block map is small: about 80 m between places


def test_the_decider_picks_real_places_with_a_reason_and_no_fallback():
    scenario = scenarios.build("city", 1)
    sim = scenario.sim
    Decider.load(seed=1).decide(sim)
    log = sim.decision_log
    assert len(log) == len(sim.cars) + len(sim.pedestrians)
    assert all(not d["fallback"] and "student model" in d["reason"] for d in log)
    assert len({d["to_place"] for d in log}) > 15   # not everybody heads for the same place


def test_at_night_the_decider_sends_far_fewer_people_to_closed_places_than_chance():
    names = {}
    for decider in (Decider.load(seed=1, start_hour=3), Decider(None, seed=1)):
        sim = scenarios.build("city", 1).sim
        decider.decide(sim)
        names[decider.student is not None] = [d["to_place"] for d in sim.decision_log]
    cats = {p["name"]: p["category"] for p in scenarios.build("city", 1).sim.places}
    shut = lambda who: mean(not is_open(cats[n], 3) for n in names[who])  # noqa: E731
    assert shut(True) < 0.5 * shut(False)


def test_without_a_model_the_sim_still_chooses_places():
    sim = scenarios.build("city", 1).sim
    Decider(None).decide(sim)
    assert sim.decision_log and all(d["fallback"] for d in sim.decision_log)


def test_a_crash_makes_the_decider_steer_people_away_from_it():
    """Same people, same places; with a crash by one place, fewer choose it."""
    def picks(with_crash: bool) -> int:
        sim = scenarios.build("city", 1).sim
        target = next(p for p in sim.places if p["category"] == "cafe")
        if with_crash:
            sim.accidents.append({"id": "acc1", "kind": "car_car", "x": target["x"], "y": target["y"],
                                  "cleared_t": None})
        decider = Decider.load(seed=5, temperature=1.0)
        total = 0
        for _ in range(8):   # repeat the same decisions to average out the sampling
            for entity in list(sim.cars.values()) + list(sim.pedestrians.values()):
                place_id, _ = decider.choose(sim, entity, "car" if hasattr(entity, "params") else "pedestrian")
                total += place_id == target["id"]
        return total

    assert picks(True) < picks(False)


def test_agents_snapshot_describes_everyone_and_matches_their_decisions():
    import json
    from collections import Counter

    scenario = scenarios.build("city", 1)
    sim = scenario.sim
    decider = Decider.load(seed=1)
    decider.decide(sim)
    agents = decider.agents(sim)
    json.dumps(agents)   # the route sends it as is
    assert len(agents) == len(sim.cars) + len(sim.pedestrians)
    assert Counter(a["kind"] for a in agents) == {"car": len(sim.cars), "pedestrian": len(sim.pedestrians)}
    went = {d["entity_id"]: d["to_place"] for d in sim.decision_log}
    for a in agents:
        assert set(a["traits"]) == set(TRAITS) and 0 <= a["probability"] <= 1
        assert a["destination"]["name"] == went[a["id"]] and a["decided_at_s"] == 0.0
        assert len(a["alternatives"]) == 3 and a["destination"]["name"] not in {x["name"] for x in a["alternatives"]}
        assert a["label"] == next(c for c in (sim.cars | sim.pedestrians).values() if c.id == a["id"]).persona


def test_history_keeps_the_last_choices_and_the_newest_is_the_destination():
    sim = scenarios.build("city", 1).sim
    decider = Decider.load(seed=2)
    entity = next(iter(sim.pedestrians.values()))
    for _ in range(5):
        decider.choose(sim, entity, "pedestrian")
        sim._sim_time += 10
    agent = next(a for a in decider.agents(sim) if a["id"] == entity.id)
    assert len(agent["history"]) == 2 and agent["decided_at_s"] == 40.0   # 3 kept: 2 past + the newest
    assert [h["t"] for h in agent["history"]] == [20.0, 30.0]


def test_someone_who_has_not_decided_has_no_destination():
    sim = scenarios.build("city", 1).sim
    agent = Decider.load(seed=1).agents(sim)[0]
    assert agent["destination"] is None and agent["alternatives"] == [] and agent["traits"]


def test_the_map_names_the_places_for_the_viewer():
    from twin.world.record import map_section

    sim = scenarios.build("city", 1).sim
    places = map_section(sim)["places"]
    assert len(places) == len(sim.places) and set(places[0]) == {"id", "name", "category", "x", "y", "building_id"}


def test_every_place_is_a_real_building_and_each_building_is_one_place():
    sim = scenarios.build("city", 1).sim
    ids = [p["building_id"] for p in sim.places]
    assert sorted(ids) == sorted(sim.buildings)          # one place per 3D building, none virtual
    for p in sim.places:
        b = sim.buildings[p["building_id"]]
        assert (p["x"], p["y"]) == b.front               # a place stands where its building is reached from the street
    assert len({p["name"] for p in sim.places}) == len(sim.places)


def test_the_buildings_keep_the_mix_of_places_and_leave_the_hospital_to_its_station():
    from collections import Counter

    sim = scenarios.build("city", 1).sim
    kinds = Counter(p["category"] for p in sim.places)
    assert kinds["home"] == max(kinds.values()) and kinds["home"] >= 8
    assert "hospital" not in kinds and {"office", "grocery", "restaurant", "school"} <= set(kinds)
    assert [p["name"] for p in sim.places] == [p["name"] for p in scenarios.build("city", 1).sim.places]   # same map, same places


def test_without_buildings_the_places_are_still_scattered_as_before():
    from twin.engine.places import TOTAL_PLACES
    from twin.engine.sim import Simulation
    from twin.world.buildings import build_buildings  # noqa: F401  (buildings are what switches the rule)
    from twin.city.two_blocks import TwoBlocksCity  # noqa: F401
    from twin.world.scenario import build_two_blocks_graph

    sim = Simulation(graph=build_two_blocks_graph())
    assert len(sim.places) == TOTAL_PLACES and all("building_id" not in p for p in sim.places)
