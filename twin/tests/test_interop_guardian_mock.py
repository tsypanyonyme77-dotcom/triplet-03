"""Twin output must be accepted by the Guardian mock; tampering and replays must not."""
import asyncio
import copy

from fastapi.testclient import TestClient

from twin.city.two_blocks import TwoBlocksCity
from twin.config import Settings
from twin.emitter import Emitter
from twin.events import EventLog

KEY = "dev-only-hmac-key"


def readings():
    em = Emitter(Settings(hmac_key=KEY), TwoBlocksCity("ped-hit"), EventLog("twin"))
    return asyncio.run(em.tick())


def test_twin_readings_are_trusted(guardian_mock):
    c = TestClient(guardian_mock.app)
    all_readings = readings()
    for r in all_readings:
        v = c.post("/ingest", json=r).json()
        assert v["trust"] == "trusted", v
    items = c.get("/verified/readings").json()["items"]
    assert len(items) == len(all_readings) and all(x["verdict"]["verdict_id"].startswith("verdict-") for x in items)


def test_tampered_reading_is_untrusted(guardian_mock):
    c = TestClient(guardian_mock.app)
    r = copy.deepcopy(readings()[0])
    r["value"]["vehicle_count"] = 99
    v = c.post("/ingest", json=r).json()
    assert v["trust"] == "untrusted" and any("HMAC" in x for x in v["reasons"])
    assert c.get("/verified/readings").json()["items"] == []


def test_replay_is_untrusted(guardian_mock):
    c = TestClient(guardian_mock.app)
    r = readings()[0]
    assert c.post("/ingest", json=r).json()["trust"] == "trusted"
    again = c.post("/ingest", json=r).json()
    assert again["trust"] == "untrusted" and any("sequence_no" in x for x in again["reasons"])


def test_malformed_body_is_a_clear_400(guardian_mock):
    c = TestClient(guardian_mock.app)
    assert c.post("/ingest", json=[1, 2]).status_code == 400
    assert c.post("/ingest", json={"sensor_id": "x"}).json()["trust"] == "untrusted"


def test_an_operator_can_mark_a_sensor_untrusted_and_restore_it(guardian_mock):
    c = TestClient(guardian_mock.app)
    em = Emitter(Settings(hmac_key=KEY), TwoBlocksCity("ped-hit"), EventLog("twin"))
    assert c.post("/api/sensors/cam-n2/trust", json={"trust": False, "reason": "looks stuck"}).json()["overruled"] == "looks stuck"
    verdicts = {r["sensor_id"]: c.post("/ingest", json=r).json() for r in asyncio.run(em.tick())}
    assert verdicts["cam-n2"]["trust"] == "untrusted" and "looks stuck" in verdicts["cam-n2"]["reasons"][0]
    assert verdicts["cam-n5"]["trust"] == "trusted"
    assert c.get("/api/readings").json()["items"]
    c.post("/api/sensors/cam-n2/trust", json={"trust": True})
    verdicts = {r["sensor_id"]: c.post("/ingest", json=r).json() for r in asyncio.run(em.tick())}
    assert verdicts["cam-n2"]["trust"] == "trusted"
