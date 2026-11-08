"""The fire truck: dispatched like the other units, drives to the building, puts the fire out, goes home."""
import math

from twin.world.scenario import DT, build_simulation, decide_randomly


def _city(**kwargs):
    return build_simulation(cars=kwargs.pop("cars", 3), pedestrians=kwargs.pop("pedestrians", 3), seed=kwargs.pop("seed", 7), **kwargs)


def _run(sim, seconds: float, until=None) -> None:
    for _ in range(round(seconds / DT)):
        decide_randomly(sim)
        sim.tick(DT)
        if until is not None and until():
            return


def _kinds(sim) -> list[str]:
    return [e["kind"] for e in sim.timeline]


def _burning_and_noticed(sim, *buildings: str) -> str:
    for b in buildings:
        sim.ignite_building(b)
    _run(sim, 6.0)
    return sim.fire.fires[0]["incident_id"]


def test_the_truck_drives_to_the_burning_building_and_puts_the_fire_out():
    sim = _city()
    incident = _burning_and_noticed(sim, "bld-01-03")
    sent = sim.dispatch_unit("fire", incident)
    assert sent["status"] == "dispatched" and sent["unit_id"] == "fire1" and 0 < sent["eta_seconds"] < 60
    truck = sim.units["fire1"]
    assert truck.status == "dispatched" and truck.siren
    fire = sim.fire.fires[0]
    _run(sim, 150.0, until=lambda: fire["cleared_t"] is not None)
    assert fire["cleared_t"] is not None
    arrived = next(e for e in sim.timeline if e["kind"] == "unit_arrived")
    assert math.hypot(arrived["x"] - fire["x"], arrived["y"] - fire["y"]) < 25.0     # stopped in the street in front of it
    cleared = next(e for e in sim.timeline if e["kind"] == "fire_extinguished")
    assert cleared["t"] - arrived["t"] >= 4.0 - 1e-6 and cleared["unit_id"] == "fire1"
    assert sim.fire.open() == [] and sim.state()["fires"] == []
    _run(sim, 200.0, until=lambda: truck.status == "idle")
    assert truck.status == "idle" and truck.finished
    order = [k for k in _kinds(sim) if k in ("fire_started", "smoke_detected", "unit_dispatched", "unit_pulled_out", "unit_arrived",
                                              "firefighting_started", "fire_extinguished", "scene_cleared", "unit_left_scene",
                                              "unit_back_at_station", "incident_phase")]
    assert [k for k in order if k != "incident_phase"] == [
        "fire_started", "smoke_detected", "unit_dispatched", "unit_pulled_out", "unit_arrived", "firefighting_started",
        "fire_extinguished", "scene_cleared", "unit_left_scene", "unit_back_at_station"]
    phases = [e["phase"] for e in sim.timeline if e["kind"] == "incident_phase"]
    assert phases == ["on_scene", "firefighting", "cleared", "closed"]
    assert sim.responses[incident]["phase"] == "closed"


def test_a_second_dispatch_for_the_same_incident_is_a_duplicate():
    sim = _city()
    incident = _burning_and_noticed(sim, "bld-01-03")
    first = sim.dispatch_unit("fire", incident)
    assert first["status"] == "dispatched"
    assert sim.dispatch_unit("fire", incident) == {"status": "duplicate", "unit_id": first["unit_id"]}


def test_the_truck_puts_out_every_burning_building_joined_to_the_first_one_by_one():
    sim = _city()
    neighbour = sim.fire.next_to["bld-01-03"][0]
    incident = _burning_and_noticed(sim, "bld-01-03", neighbour)
    assert sim.fire.fires[1]["incident_id"] == incident                      # one incident for both
    sim.dispatch_unit("fire", incident)
    _run(sim, 200.0, until=lambda: not sim.fire.open())
    assert not sim.fire.open()
    out = [e for e in sim.timeline if e["kind"] == "fire_extinguished"]
    assert len(out) == 2 and out[1]["t"] - out[0]["t"] >= 4.0 - 1e-6        # one after the other, 4 s each
    assert len([e for e in sim.timeline if e["kind"] == "scene_cleared"]) == 1


def test_a_building_that_catches_fire_while_the_truck_works_is_put_out_too():
    sim = _city()
    incident = _burning_and_noticed(sim, "bld-01-03")
    sim.dispatch_unit("fire", incident)
    _run(sim, 150.0, until=lambda: sim.units["fire1"].status == "on_scene")
    neighbour = sim.fire.next_to["bld-01-03"][0]
    assert sim.ignite_building(neighbour, cause="spread")["status"] == "ignited"
    _run(sim, 100.0, until=lambda: not sim.fire.open())
    assert not sim.fire.open() and len([e for e in sim.timeline if e["kind"] == "fire_extinguished"]) == 2


def test_police_sent_to_a_fire_look_round_and_leave_while_the_truck_works():
    sim = _city()
    incident = _burning_and_noticed(sim, "bld-01-03")
    sim.dispatch_unit("police", incident)
    sim.dispatch_unit("fire", incident)
    _run(sim, 400.0, until=lambda: sim.responses[incident]["phase"] == "closed")
    assert sim.responses[incident]["phase"] == "closed" and not sim.fire.open()
    assert {u.status for u in sim.units.values()} == {"idle"}
    assert "unit_left_scene" in _kinds(sim)
    assert [e["unit_id"] for e in sim.timeline if e["kind"] == "fire_extinguished"] == ["fire1"]


def test_without_a_truck_the_fire_burns_on_and_the_response_stays_open():
    sim = _city()
    incident = _burning_and_noticed(sim, "bld-01-03")
    sim.dispatch_unit("police", incident)
    _run(sim, 150.0)
    assert sim.fire.open() and sim.responses[incident]["phase"] != "closed"


def test_a_truck_sent_after_the_fire_is_out_finds_nothing_and_goes_home():
    sim = _city()
    incident = _burning_and_noticed(sim, "bld-01-03")
    sim.fire.extinguish("fire-0001", sim._sim_time)
    assert sim.dispatch_unit("fire", incident)["status"] == "dispatched"
    _run(sim, 300.0, until=lambda: sim.responses[incident]["phase"] == "closed")
    assert sim.units["fire1"].status == "idle" and sim.responses[incident]["phase"] == "closed"


def test_putting_the_fire_out_ends_the_avoidance():
    sim = _city()
    incident = _burning_and_noticed(sim, "bld-01-03")
    assert sim.hazard_edges
    sim.dispatch_unit("fire", incident)
    _run(sim, 200.0, until=lambda: not sim.fire.open())
    _run(sim, 1.0)
    assert sim.hazard_edges == set() and sim.hazard_walk_edges == set()


def test_a_truck_is_not_held_up_by_a_car_that_pulled_over_for_it_on_the_far_side_of_a_junction():
    """Regression: a car just past node 1 pulled over for the siren of a truck still before the corner and
    stopped in the junction's exit; the truck waited for it, and the car stays pulled over until the truck
    has passed, so neither moved. A car now pulls over only for a siren on its own edge."""
    from twin.world import scenarios

    for seed in (7, 3, 11, 1, 2, 5):
        sc = scenarios.build("building-fire", seed=seed)
        sim, called = sc.sim, False
        for _ in range(round(150 / DT)):
            sc.step()
            if sim.fire.fires and not called:
                called = sim.dispatch_unit("fire", sim.fire.fires[0]["incident_id"])["status"] == "dispatched"
            if called and sim.fire.fires[0]["cleared_t"] is not None:
                break
        first = sim.fire.fires[0]
        assert first["cleared_t"] is not None, f"seed {seed}: the truck never put the fire out"
        assert first["cleared_t"] - first["t"] < 80.0, f"seed {seed}: put out after {first['cleared_t'] - first['t']:.0f} s"
