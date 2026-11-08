"""Stations: every emergency vehicle starts parked in its station bay, is recorded from the
first frame, pulls out of the bay when called, and parks back in it. No pop-in, no teleport."""
import math

from twin.engine.parking import spot_front_pose
from tools.continuity import check
from twin.world import scenarios
from twin.world.map import STATIONS
from twin.world.record import frame
from twin.world.scenario import DT
from twin.world.scenarios import CityParams


def test_each_station_has_its_vehicle_parked_in_its_bay_at_the_start():
    sim = scenarios.build("city").sim
    kinds = {u.station_id: u.kind for u in sim.units.values()}
    assert kinds == {"hospital": "ambulance", "police_station": "police", "fire_station": "fire"}
    for unit in sim.units.values():
        spot = sim.parking_spots[unit.home_spot_id]
        assert spot.occupied_by == unit.id
        x, y, h = spot_front_pose(sim.graph, spot, unit.params.length)
        assert (unit.status, unit.finished) == ("idle", True)
        assert math.hypot(unit.x - x, unit.y - y) < 1e-6 and abs(unit.heading - h) < 1e-6


def test_units_are_in_the_first_recorded_frame_with_their_kind():
    sc = scenarios.build("city")
    sc.step()
    rows = {row[0]: row for row in frame(sc.sim, DT)["cars"] if row[0] in sc.sim.units}
    assert {r[5] for r in rows.values()} == {"ambulance", "police", "fire"}
    assert all(r[8] == "idle" for r in rows.values())


def test_no_civilian_car_ever_takes_a_station_bay():
    sc = scenarios.build("city", params=CityParams(scenarios.MAX_CARS, scenarios.MAX_PEDESTRIANS, 0.0, 0.0))
    bays = {spot_id for st in STATIONS for spot_id in st.spot_ids}
    for _ in range(int(60 / DT)):
        sc.step()
        for spot_id in bays:
            assert sc.sim.parking_spots[spot_id].occupied_by in sc.sim.units


def test_a_called_ambulance_drives_out_of_its_bay_and_parks_back_in_it_continuously():
    sc = scenarios.run("ped-hit", 60.0)
    sim = sc.sim
    amb = sim.units["amb1"]
    home = (amb.x, amb.y, amb.heading)
    accident = sim.accidents[0]
    assert sim.dispatch_ambulance(accident["id"])
    frames, statuses = [], []
    for _ in range(int(240 / DT)):
        sc.step()
        frames.append(frame(sim, sim._sim_time))
        statuses.append(amb.status)
        if amb.status == "idle" and accident["cleared_t"] is not None:
            break
    assert accident["cleared_t"] is not None
    assert [s for i, s in enumerate(statuses) if i == 0 or s != statuses[i - 1]] == ["dispatched", "cleaning", "returning", "idle"]
    assert math.hypot(amb.x - home[0], amb.y - home[1]) < 0.3      # back in its bay, as a car parks
    assert abs(math.atan2(math.sin(amb.heading - home[2]), math.cos(amb.heading - home[2]))) < math.radians(4)
    # the ambulance itself moves continuously the whole way (the wreck and the injured
    # pedestrian still vanish when cleared: towing and loading come with the dispatch step)
    only_amb = [{"t": f["t"], "cars": [r for r in f["cars"] if r[0] == "amb1"], "pedestrians": []} for f in frames]
    assert sum(check(only_amb, entries=[])["violations"].values()) == 0
