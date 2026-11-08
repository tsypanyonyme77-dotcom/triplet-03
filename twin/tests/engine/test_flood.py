"""The water model (engine/flood.py): rain, the dip's depth, drain and pump, where it is wet."""
import math

import pytest

from twin.engine import flood as fl
from twin.engine.flood import FloodZone, RainProfile
from twin.world import scenarios as _scenarios
from twin.world.scenarios import CityParams


def _zone(**kw) -> FloodZone:
    spec = dict(id="dip", street=(2, 3), ax=80.0, ay=0.0, bx=160.0, by=0.0, centre_s=38.0, half_length_m=24.0,
                dip_depth_m=0.5, road_half_width_m=8.0, sidewalk_width_m=4.0, catchment_m2=80_000.0, pump_id="pump")
    return FloodZone(**{**spec, **kw})


def test_rain_is_linear_between_points_and_dry_outside():
    rain = RainProfile(((10.0, 0.0), (30.0, 120.0), (150.0, 120.0), (180.0, 0.0)))
    assert rain.intensity(0.0) == 0.0
    assert rain.intensity(20.0) == pytest.approx(60.0)
    assert rain.intensity(100.0) == 120.0
    assert rain.intensity(165.0) == pytest.approx(60.0)
    assert rain.intensity(500.0) == 0.0
    assert RainProfile().intensity(50.0) == 0.0


def test_depth_and_volume_are_inverse_and_follow_the_parabolic_dip():
    z = _zone()
    for d in (0.05, 0.2, 0.3, 0.45):
        z.volume_m3 = z.volume_at(d)
        assert z.depth_m == pytest.approx(d)
        assert z.wet_half_length_m == pytest.approx(24.0 * math.sqrt(d / 0.5))
    # V = 4/3 W L d^1.5 / sqrt(H)
    assert z.volume_at(0.5) == pytest.approx(4 / 3 * 16.0 * 24.0 * 0.5)


def test_rain_fills_the_dip_by_the_rational_method_and_the_drain_empties_it():
    z = _zone()
    z.step(1.0, 120.0)
    assert z.inflow_m3s == pytest.approx(0.9 * 120.0 / 1000 / 3600 * 80_000.0)   # Q = C i A = 2.4 m3/s
    assert z.outflow_m3s == pytest.approx(0.3)                                     # the drain at capacity
    assert z.volume_m3 == pytest.approx(2.4 - 0.3)
    for _ in range(100):
        z.step(1.0, 0.0)
    assert z.volume_m3 == 0.0 and z.depth_m == 0.0 and z.outflow_m3s == 0.0      # empties, never below zero


def test_the_pump_adds_its_capacity_and_the_depth_stops_where_the_water_spills_on():
    dry, pumped = _zone(), _zone(pump_on=True)
    for z in (dry, pumped):
        z.volume_m3 = z.volume_at(0.4)
        z.step(1.0, 0.0)
    assert dry.outflow_m3s == pytest.approx(0.3) and pumped.outflow_m3s == pytest.approx(1.5)
    full = _zone()
    for _ in range(2000):
        full.step(1.0, 120.0)
    assert full.depth_m == pytest.approx(fl.MAX_DEPTH_M)


def test_depth_at_a_point_is_deepest_at_the_low_point_and_only_above_the_kerb_on_the_sidewalk():
    z = _zone()
    z.volume_m3 = z.volume_at(0.4)
    assert z.depth_at(118.0, 2.5) == pytest.approx(0.4)                     # the low point, in a lane
    assert z.depth_at(118.0 + 12.0, 0.0) == pytest.approx(0.4 - 0.5 * 0.25)  # half way up the dip
    assert z.depth_at(118.0 + 24.0, 0.0) == 0.0                             # past the dip
    assert z.depth_at(118.0, 10.0) == pytest.approx(0.4 - fl.KERB_HEIGHT_M)  # on the sidewalk
    assert z.depth_at(118.0, 13.0) == 0.0                                   # in the block
    z.volume_m3 = z.volume_at(0.1)
    assert z.depth_at(118.0, 10.0) == 0.0                                   # the kerb keeps it on the road


# ---- a drain in every street, the flood simulator, and flood_risk -------------------------


def _quiet_city(seed=1, **risk):
    return _scenarios.build("city", seed, CityParams(cars=12, pedestrians=12, car_crash_risk=0.0, ped_hit_risk=0.0, **risk))


def test_every_street_has_a_drain():
    sim = _quiet_city().sim
    assert len(sim.flood_zones) == 7 and sim.flood_zones[0].id == "dip-2-3"
    assert {z.street for z in sim.flood_zones} == {(1, 2), (2, 3), (4, 5), (5, 6), (1, 4), (2, 5), (3, 6)}


def test_flooding_a_street_blocks_its_drain_and_rains_there_only():
    sc = _quiet_city()
    sim = sc.sim
    first = sim.flood_street("dip-1-4")
    assert first["status"] == "started" and first["street"] == "1-4" and first["pump_id"] == "pump-1-4"
    assert sim.flood_street("dip-1-4")["status"] == "duplicate"
    assert sim.flood_street("dip-9-9") == {"status": "rejected", "reason": "unknown_zone"}
    for _ in range(1500):  # 150 s
        sc.step()
    zones = {z.id: z for z in sim.flood_zones}
    assert zones["dip-1-4"].drain_blocked and zones["dip-1-4"].depth_m >= 0.2
    assert (1, 4) in sim.flooded_edges and (4, 1) in sim.flooded_edges
    assert all(z.depth_m == 0.0 for zid, z in zones.items() if zid != "dip-1-4")
    kinds = [(e["kind"], e.get("zone_id")) for e in sim.timeline]
    assert ("flood_triggered", "dip-1-4") in kinds and ("street_flooded", "dip-1-4") in kinds


def test_a_blocked_drain_only_empties_by_the_pump_and_then_clears():
    sc = _quiet_city()
    sim = sc.sim
    sim.flood_street("dip-2-5")
    for _ in range(2500):  # 250 s: the downpour is over
        sc.step()
    zone = next(z for z in sim.flood_zones if z.id == "dip-2-5")
    held = zone.depth_m
    assert held > 0.2
    for _ in range(300):  # 30 s more, no rain: a blocked drain takes nothing
        sc.step()
    assert zone.depth_m == pytest.approx(held)
    sim.set_pump("on", pump_id="pump-2-5")
    for _ in range(3000):
        sc.step()
        if not zone.drain_blocked:
            break
    assert zone.depth_m == 0.0 and not zone.drain_blocked
    assert "drain_cleared" in [e["kind"] for e in sim.timeline]


def test_flood_risk_floods_some_streets_on_its_own_and_never_changes_the_traffic():
    plain, risky = _quiet_city(seed=3), _quiet_city(seed=3, flood_risk=0.5)
    assert not plain.sim._planned_floods and risky.sim._planned_floods
    assert all(20.0 <= t <= 150.0 for t in risky.sim._planned_floods.values())
    planned = set(risky.sim._planned_floods)
    for _ in range(1600):
        plain.step()
        risky.step()
    triggered = {e["zone_id"] for e in risky.sim.timeline if e["kind"] == "flood_triggered"}
    assert triggered == planned and not risky.sim._planned_floods
    assert all(e.get("cause") == "random" for e in risky.sim.timeline if e["kind"] == "flood_triggered")
    # the same people were drawn: flood_risk has its own random generator
    assert [p.id for p in plain.sim.pedestrians.values()] == [p.id for p in risky.sim.pedestrians.values()]
    assert [c.obeys_signals for c in plain.sim.cars.values()] == [c.obeys_signals for c in risky.sim.cars.values()]


def test_reckless_road_users_ignore_the_water():
    sim = _scenarios.build("city", 1, CityParams(cars=20, pedestrians=40, car_crash_risk=0.5, ped_hit_risk=0.5)).sim
    assert all(c.ignores_flood == (not c.obeys_signals) for c in sim.cars.values())
    assert all(p.ignores_flood == p.distracted for p in sim.pedestrians.values())
    assert any(c.ignores_flood for c in sim.cars.values()) and any(p.ignores_flood for p in sim.pedestrians.values())
