"""Witnesses call the emergency number; the call centre merges their calls; cameras flag crashes."""
import math

from twin.engine import witnesses as wit
from twin.engine.emergency_calls import CallCentre
from tools.check_rules import run_movement_checks, rule_violations
from twin.world import scenarios
from twin.world.scenario import DT
from twin.world.scenarios import CityParams


def test_buildings_block_the_view_streets_do_not():
    sim = scenarios.build("city").sim
    c = sim.corridors
    assert c.line_of_sight(10.0, -10.0, 70.0, -10.0)        # along the south sidewalk
    assert c.line_of_sight(-10.0, 10.0, 10.0, -10.0)        # round the corner over the junction
    assert not c.line_of_sight(40.0, -10.0, 40.0, 90.0)     # straight through block A
    assert not c.line_of_sight(20.0, -10.0, 60.0, 90.0)


def test_calls_about_one_spot_merge_into_one_incident_and_far_ones_do_not():
    cc = CallCentre()
    a = cc.receive(10.0, "p1", "pedestrian", {"x": 70.0, "y": -2.0, "category": "medical", "caller_confidence": 0.8}, "acc1")
    b = cc.receive(14.0, "p2", "pedestrian", {"x": 74.0, "y": 3.0, "category": "police", "caller_confidence": 0.7}, "acc1")
    c = cc.receive(15.0, "p3", "pedestrian", {"x": 150.0, "y": 80.0, "category": "medical", "caller_confidence": 0.5}, None)
    d = cc.receive(400.0, "p4", "pedestrian", {"x": 70.0, "y": -2.0, "category": "medical", "caller_confidence": 0.8}, "acc1")
    assert a["incident_id"] == b["incident_id"] == "inc-0001"
    assert c["incident_id"] == "inc-0002"     # elsewhere: its own incident
    assert d["incident_id"] == "inc-0003"     # long after the last call: a new incident
    assert [x["call_id"] for x in cc.calls] == ["call-0001", "call-0002", "call-0003", "call-0004"]


def test_witnesses_call_after_reacting_stand_still_while_calling_and_walk_on():
    sc = scenarios.build("ped-hit", seed=7)
    sim = sc.sim
    positions: dict[str, list] = {}
    for _ in range(int(90 / DT)):
        sc.step()
        for call in sim.active_calls():
            if call["reporter_kind"] == "pedestrian":
                p = sim.pedestrians[call["reporter_id"]]
                positions.setdefault(call["call_id"], []).append((p.x, p.y, math.hypot(p.force.vx, p.force.vy)))
    incident = next(e for e in sim.timeline if e["kind"] == "incident")
    started = [e for e in sim.timeline if e["kind"] == "call_started"]
    noticed = {e["reporter_id"]: e["t"] for e in sim.timeline if e["kind"] == "witness_noticed"}
    assert started and {e["incident_id"] for e in started} == {"inc-0001"}
    for e in started:
        assert e["t"] >= noticed[e["reporter_id"]] + wit.REACTION_S[0] - 1e-6
        assert e["t"] >= incident["t"]
    assert positions, "no pedestrian witness on the phone in this run"
    for samples in positions.values():
        settled = samples[15:]   # 1.5 s to come to a stop
        assert all(v < 0.1 for _, _, v in settled)
        assert max(math.hypot(x - settled[0][0], y - settled[0][1]) for x, y, _ in settled) < 0.3
    ended = {e["reporter_id"] for e in sim.timeline if e["kind"] == "call_ended"}
    for rid in ended & set(sim.pedestrians):
        assert sim.pedestrians[rid].status != "calling"


def test_callers_keep_the_movement_rules():
    result = run_movement_checks(90.0, scenario=scenarios.build("ped-hit", seed=7))
    assert rule_violations(result) == {}


def test_a_false_report_is_a_call_about_nothing():
    sc = scenarios.build("city", seed=3, params=CityParams().clean())
    sc.sim.false_call_rate_per_min = 20.0
    for _ in range(int(40 / DT)):
        sc.step()
    calls = sc.sim.call_centre.calls
    assert calls and all(c["truth_accident_id"] is None for c in calls) and not sc.sim.accidents


def test_a_camera_flags_the_crash_a_few_seconds_after_it_and_clean_traffic_never_as_a_collision():
    sim = scenarios.run("car-crash", 65.0).sim
    crash_t = sim.accidents[0]["t"]
    flagged = [e for e in sim.timeline if e["kind"] == "camera_anomaly" and e["anomaly_type"] == "collision"]
    assert flagged and crash_t + 1.0 <= flagged[0]["t"] <= crash_t + 4.0
    clean = scenarios.run("city", 120.0, params=CityParams().clean()).sim
    # a car queuing over 30 s is a true stopped_vehicle alert, but it must not become an incident
    assert not [e for e in clean.timeline if e["kind"] == "camera_anomaly" and e["anomaly_type"] == "collision"]
    assert not clean.call_centre.incidents
