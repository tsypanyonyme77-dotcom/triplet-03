"""Building fires: they start, grow, spread to touching buildings, and go out."""
import random

from twin.engine.fires import RAMP_S, SPREAD_DELAY_S, FireModel
from twin.world import scenarios
from twin.world.buildings import build_buildings
from twin.world.map import build_two_blocks_graph
from twin.world.record import frame
from twin.world.scenario import DT, build_simulation
from twin.world.scenarios import CityParams


def _model(seed: int = 1) -> FireModel:
    return FireModel({b.id: b for b in build_buildings(build_two_blocks_graph())}, seed)


def test_a_fire_is_a_record_at_the_buildings_front_and_ignites_only_once():
    model = _model()
    fire = model.ignite("bld-01-01", 10.0, "operator")
    assert fire["kind"] == "building_fire" and fire["cleared_t"] is None and fire["cause"] == "operator"
    assert (fire["x"], fire["y"]) == model.buildings["bld-01-01"].front
    assert model.ignite("bld-01-01", 11.0, "operator") is None      # already burning
    assert model.ignite("bld-99-99", 11.0, "operator") is None      # no such building
    assert model.burning("bld-01-01") is fire and model.open() == [fire]


def test_a_fire_grows_to_full_strength_then_stays_until_put_out():
    model = _model()
    fire = model.ignite("bld-01-01", 10.0, "operator")
    assert model.intensity(fire, 10.0) == 0.0
    assert 0.4 < model.intensity(fire, 10.0 + RAMP_S / 2) < 0.6
    assert model.intensity(fire, 10.0 + 5 * RAMP_S) == 1.0
    assert model.extinguish(fire["id"], 90.0) and fire["cleared_t"] == 90.0
    assert model.intensity(fire, 95.0) == 0.0 and model.open() == []
    assert not model.extinguish(fire["id"], 91.0)                   # already out
    assert model.ignite("bld-01-01", 100.0, "operator")["id"] != fire["id"]   # it can burn again


def test_a_fire_spreads_only_after_a_delay_and_only_to_touching_buildings():
    model = _model(seed=3)
    first = model.ignite("bld-01-01", 0.0, "operator")
    started = []
    t = 0.0
    while t < 400.0:
        t += 1.0
        for fire in model.tick(t):
            started.append((t, fire))
    assert started, "nothing spread in 400 s"
    assert min(t for t, _ in started) >= SPREAD_DELAY_S
    for _, fire in started:
        assert fire["cause"] == "spread"
        source = model.get(fire["source_fire_id"])
        assert fire["building_id"] in model.next_to[source["building_id"]]
    assert {f["building_id"][:6] for _, f in started} == {"bld-01"}   # never across a street
    assert first["cleared_t"] is None


def test_putting_a_fire_out_stops_it_spreading():
    model = _model(seed=3)
    first = model.ignite("bld-01-01", 0.0, "operator")
    model.extinguish(first["id"], 30.0)
    assert [model.tick(float(t)) for t in range(31, 300)] == [[] for _ in range(31, 300)]


def test_a_cluster_is_the_burning_buildings_joined_through_neighbours():
    model = _model()
    a = model.ignite("bld-01-01", 0.0, "operator")
    far = model.ignite("bld-02-05", 0.0, "operator")
    assert [f["id"] for f in model.cluster(a["id"])] == [a["id"]]
    neighbour = model.next_to["bld-01-01"][0]
    b = model.ignite(neighbour, 5.0, "spread", a["id"])
    assert {f["id"] for f in model.cluster(a["id"])} == {a["id"], b["id"]}
    assert far["id"] not in {f["id"] for f in model.cluster(a["id"])}
    model.extinguish(a["id"], 9.0)
    assert model.cluster(a["id"]) == []


def test_arming_draws_fire_prone_buildings_that_catch_fire_once_inside_the_window():
    assert _model().arm(0.0) == []
    model = _model()
    assert len(model.arm(1.0, (10.0, 20.0))) == 24
    t, seen = 0.0, []
    while t < 30.0:
        t += 0.1
        seen += model.tick(t)
    assert len(seen) == 24 and all(10.0 <= f["t"] <= 20.1 and f["cause"] == "random" for f in seen)
    some = _model(seed=5).arm(0.1)
    assert some == _model(seed=5).arm(0.1) and 0 < len(some) < 24      # the same seed, the same buildings


def test_arming_leaves_the_traffics_random_numbers_alone():
    random.seed(42)
    before = random.getstate()
    _model().arm(0.5)
    assert random.getstate() == before


def test_an_operator_can_set_a_building_alight_and_it_shows_in_state_timeline_and_frame():
    sim = scenarios.build("city", params=CityParams().clean()).sim
    assert sim.ignite_building("bld-01-01") == {"status": "ignited", "fire_id": "fire-0001", "building_id": "bld-01-01"}
    assert sim.ignite_building("bld-01-01")["status"] == "duplicate"
    assert sim.ignite_building("nope") == {"status": "rejected", "reason": "unknown_building"}
    for _ in range(int(10 / DT)):
        sim.tick(DT)
    assert [e["kind"] for e in sim.timeline if e["kind"] == "fire_started"] == ["fire_started"]
    assert sim.timeline[[e["kind"] for e in sim.timeline].index("fire_started")]["cause"] == "operator"
    assert [f["building_id"] for f in sim.state()["fires"]] == ["bld-01-01"]
    row = frame(sim, sim._sim_time)["fires"]
    assert row[0][0] == "bld-01-01" and 0.0 < row[0][1] < 1.0 and row[0][2] == "fire-0001"


def test_the_fire_risk_of_the_city_sets_how_many_buildings_catch_fire_by_themselves():
    quiet = build_simulation(cars=0, pedestrians=0, fire_risk=0.0)
    risky = build_simulation(cars=0, pedestrians=0, fire_risk=1.0)
    for _ in range(int(200 / DT)):
        quiet.tick(DT)
        risky.tick(DT)
    assert quiet.fire.fires == [] and len(risky.fire.fires) >= 24
    assert CityParams(fire_risk=0.2).as_dict()["fire_risk"] == 0.2
    assert CityParams().clean().fire_risk == 0.0
