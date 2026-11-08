"""The two-blocks engine as the Twin's city: witnesses' calls and cameras become signed readings."""
import asyncio

from conftest import ALL_TYPES, send_to_guardian
from fastapi.testclient import TestClient

from twin.city.two_blocks import TwoBlocksCity
from twin.config import Settings
from twin.emitter import Emitter
from twin.events import EventLog
from twin.partners.guardian_dialect import GuardianDialect
from twin.signing import verify

KEY = "dev-only-hmac-key"
ENVELOPE = ("contract_version", "sensor_id", "type", "zone_id", "timestamp", "sequence_no", "value", "provenance")


def _run(city: TwoBlocksCity, seconds: float, interval: float = 3.0) -> tuple[list[dict], Emitter]:
    emitter = Emitter(Settings(hmac_key=KEY, emit_interval_s=interval), city, EventLog("twin"))
    readings = []
    for _ in range(round(seconds / interval)):
        readings += asyncio.run(emitter.tick())
    return readings, emitter


def test_zones_are_two_blocks_and_the_streets_with_the_stations():
    zones = {z["zone_id"]: z for z in TwoBlocksCity("city").zones()}
    blocks = {"zone-01", "zone-02", "zone-03"}
    assert blocks <= set(zones) and all(z.startswith("zone-dip-") for z in set(zones) - blocks)
    assert zones["zone-03"]["facilities"] == ["fire", "medical", "police"]
    assert all(blocks - {zid} <= set(zones[zid]["adjacent"]) for zid in blocks)
    assert all(zid in zones[other]["adjacent"] for zid, z in zones.items() for other in z["adjacent"])   # both ways


def test_witness_calls_become_signed_emergency_call_readings_merged_into_one_incident():
    city = TwoBlocksCity("ped-hit")
    readings, emitter = _run(city, 80.0)
    calls = [r for r in readings if r["type"] == "emergency_call"]
    assert len(calls) == len(city.sim.call_centre.calls) >= 1
    for r in calls:
        assert all(k in r for k in ENVELOPE) and verify(r, KEY)
        assert r["zone_id"] == "zone-03" and r["department"] in ("medical", "police", "fire")
        assert "truth_accident_id" not in r["value"]                     # ground truth stays in the Twin
    assert {r["value"]["incident_id"] for r in calls} == {"inc-0001"}  # one crash, one incident
    seqs = [r["sequence_no"] for r in calls if r["sensor_id"] == calls[0]["sensor_id"]]
    assert seqs == list(range(1, len(seqs) + 1))
    incident_t = next(e["t"] for e in city.timeline() if e["kind"] == "incident")
    assert all(r["value"]["sim_time_s"] >= incident_t + 1.0 for r in calls)  # nobody calls before reacting
    kinds = [e["kind"] for e in emitter.events.recent()]
    assert "sim_incident" in kinds and "sim_call_started" in kinds and "emergency_call_reading" in kinds


def test_a_camera_flags_the_crash_as_a_second_source():
    city = TwoBlocksCity("car-crash")
    readings, _ = _run(city, 65.0)
    anomalies = [r for r in readings if r["type"] == "cctv_anomaly" and r["value"]["anomaly_type"] == "collision"]
    assert anomalies and all(verify(r, KEY) for r in anomalies)
    incident_t = next(e["t"] for e in city.timeline() if e["kind"] == "incident")
    assert min(r["value"]["since_sim_s"] for r in anomalies) >= incident_t
    cams = [r for r in readings if r["type"] == "traffic_camera"]
    assert {r["sensor_id"] for r in cams} == {"cam-n2", "cam-n5", "cam-zone-01", "cam-zone-02"}
    assert all(0.0 <= r["value"]["congestion_score"] <= 1.0 for r in cams)


def test_a_false_report_opens_its_own_incident():
    city = TwoBlocksCity("city", seed=3)
    city.sim.false_call_rate_per_min = 30.0
    city.step(30.0)
    false = [c for c in city.sim.call_centre.calls if c["truth_accident_id"] is None]
    assert false
    real_incidents = {c["incident_id"] for c in city.sim.call_centre.calls if c["truth_accident_id"] is not None}
    assert false[0]["incident_id"] not in real_incidents or not real_incidents


def test_the_guardian_mock_trusts_the_new_readings(guardian_mock):
    readings, _ = _run(TwoBlocksCity("ped-hit"), 65.0)
    client = TestClient(guardian_mock.app)
    dialect = GuardianDialect(guardian_mock.HMAC_KEY, ALL_TYPES)
    verdicts = [v for r in readings if (v := send_to_guardian(client, r, dialect)) is not None]
    assert verdicts and all(v["status"] == "trusted" for v in verdicts), [v for v in verdicts if v["status"] != "trusted"][:2]


def test_flood_rain_gauge_and_water_level_are_signed_consistent_readings():
    city = TwoBlocksCity("flood")
    readings, _ = _run(city, 120.0)
    rain = [r for r in readings if r["type"] == "rainfall"]
    level = [r for r in readings if r["type"] == "water_level"]
    streets = len(city.sim.flood_zones)
    assert streets == 7 and len(rain) == len(level) == 40 * streets     # one of each per street per emit tick: a heartbeat
    for r in rain + level:
        assert all(k in r for k in ENVELOPE) and verify(r, KEY) and r["department"] == "water"
    here_level = [r for r in level if r["sensor_id"] == "wl-dip-2-3"]
    here_rain = [r for r in rain if r["sensor_id"] == "rain-dip-2-3"]
    assert {r["zone_id"] for r in here_level} == {"zone-dip-2-3"} and {r["zone_id"] for r in here_rain} == {"zone-03"}
    assert max(r["value"]["mm_per_hr"] for r in here_rain) == 120.0
    assert max(r["value"]["mm_per_hr"] for r in rain) == 120.0 and len({r["value"]["mm_per_hr"] for r in rain[:7]}) == 1  # one cloud over the map
    assert all(r["value"]["level_m"] == 0.0 for r in level if r["sensor_id"] != "wl-dip-2-3")
    depths = [r["value"]["level_m"] for r in here_level]
    assert depths == sorted(depths) and depths[-1] > 0.3                   # it only rises while it rains
    # the Guardian's rule: no rise over 0.2 m in 5 s without matching rain
    assert all(b["value"]["level_m"] - a["value"]["level_m"] < 0.2 for a, b in zip(here_level, here_level[1:]))
    calls = [r for r in readings if r["type"] == "emergency_call"]
    assert calls and {r["department"] for r in calls} <= {"fire", "medical", "police"}
    assert {"wl-dip-2-3", "rain-dip-2-3", "wl-dip-1-2", "rain-dip-1-2"} <= city.device_ids()
