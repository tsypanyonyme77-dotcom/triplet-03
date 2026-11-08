"""Twin output must be accepted by the Guardian mock; tampering and replays must not."""
import asyncio
import copy

import httpx
from conftest import ALL_TYPES, send_to_guardian
from fastapi.testclient import TestClient

from twin.city.two_blocks import TwoBlocksCity
from twin.config import Settings
from twin.emitter import Emitter
from twin.events import EventLog
from twin.partners.guardian_dialect import GuardianDialect

KEY = "dev-only-hmac-key"


def readings():
    em = Emitter(Settings(hmac_key=KEY), TwoBlocksCity("ped-hit"), EventLog("twin"))
    return asyncio.run(em.tick())


def _dialect():
    return GuardianDialect(KEY, ALL_TYPES)


def test_twin_readings_are_trusted_and_a_verdict_can_be_asked_for_by_pair(guardian_mock):
    c = TestClient(guardian_mock.app)
    dialect = _dialect()
    for r in readings():
        v = send_to_guardian(c, r, dialect)
        assert v is None or v["status"] == "trusted", v
        if v is not None:
            asked = c.post("/v1/verdicts/request", json={"sensor_id": r["sensor_id"], "sequence_no": r["sequence_no"]}).json()
            assert asked["verdict_id"] == v["verdict_id"]
    assert c.post("/v1/verdicts/request", json={"sensor_id": "cam-n2", "sequence_no": 999}).json()["status"] == "unknown"


def test_tampered_reading_is_untrusted(guardian_mock):
    c = TestClient(guardian_mock.app)
    (r,) = [x for x in readings() if x["type"] == "traffic_camera"][:1]
    envelope = copy.deepcopy(_dialect().render(r)[0])
    envelope["value"]["vehicle_count"] = 99
    v = c.post("/v1/readings", json=envelope).json()["results"][0]["verdict"]
    assert v["status"] == "untrusted" and any("HMAC" in x for x in v["reasons"])


def test_replay_is_untrusted(guardian_mock):
    c = TestClient(guardian_mock.app)
    (r,) = [x for x in readings() if x["type"] == "traffic_camera"][:1]
    dialect = _dialect()
    assert send_to_guardian(c, r, dialect)["status"] == "trusted"     # first of its sensor: sequence_reset
    again = send_to_guardian(c, r, dialect)                           # the same number, no reset
    assert again["status"] == "untrusted" and any("sequence_no" in x for x in again["reasons"])


def test_malformed_readings_are_answered_one_by_one(guardian_mock):
    c = TestClient(guardian_mock.app)
    assert c.post("/v1/readings", json=[1, 2]).json()["results"][0]["error"]["error"] == "schema_invalid"
    assert c.post("/v1/readings", json={"sensor_id": "x"}).json()["results"][0]["verdict"]["status"] == "untrusted"


def test_the_twins_key_is_checked_when_the_mock_has_one(guardian_mock, monkeypatch):
    monkeypatch.setattr(guardian_mock, "TWIN_API_KEY", "k")
    c = TestClient(guardian_mock.app)
    assert c.post("/v1/readings", json=[]).status_code == 401
    assert c.post("/v1/readings", json=[], headers={"X-API-Key": "k"}).status_code == 200


def test_an_operator_can_mark_a_sensor_untrusted_and_restore_it(guardian_mock):
    c = TestClient(guardian_mock.app)
    em = Emitter(Settings(hmac_key=KEY), TwoBlocksCity("ped-hit"), EventLog("twin"))
    assert c.post("/api/sensors/cam-n2/trust", json={"trust": False, "reason": "looks stuck"}).json()["overruled"] == "looks stuck"
    dialect = _dialect()
    verdicts = {r["sensor_id"]: send_to_guardian(c, r, dialect) for r in asyncio.run(em.tick())}
    assert verdicts["cam-n2"]["status"] == "untrusted" and "looks stuck" in verdicts["cam-n2"]["reasons"][-1]
    assert verdicts["cam-n5"]["status"] == "trusted"
    assert c.get("/api/readings").json()["items"]
    c.post("/api/sensors/cam-n2/trust", json={"trust": True})
    verdicts = {r["sensor_id"]: send_to_guardian(c, r, dialect) for r in asyncio.run(em.tick())}
    assert verdicts["cam-n2"]["status"] == "trusted"


def test_the_mock_brain_moves_past_a_reading_the_guardian_never_judges(guardian_mock, monkeypatch):
    from conftest import load_mock

    brain = load_mock("brain", "mock_brain_stuck")
    brain.TWIN_URL, brain.GUARDIAN_URL = "http://twin:1", "http://guardian:2"
    readings_ = [{"sensor_id": "never", "sequence_no": 1, "type": "traffic_camera", "zone_id": "z", "value": {}},
                 {"sensor_id": "cam", "sequence_no": 1, "type": "traffic_camera", "zone_id": "z", "value": {}}]

    def twin_and_guardian(request):
        if request.url.path == "/readings":
            at = int(request.url.params["cursor"])
            return httpx.Response(200, json={"readings": readings_[at:], "next_cursor": 2, "stream_id": "s"})
        if request.url.path == "/v1/verdicts/request":
            status = "unknown" if b"never" in request.content else "trusted"
            return httpx.Response(200, json={"verdict_id": "v", "status": status})
        return httpx.Response(404, json={})

    async def scenario():
        async with httpx.AsyncClient(transport=httpx.MockTransport(twin_and_guardian)) as client:
            for _ in range(brain.VERDICT_RETRIES + 1):
                await brain.desk.poll_once(client)

    asyncio.run(scenario())
    assert brain._cursor["at"] == 2 and [i["reading"]["sensor_id"] for i in brain.desk.readings] == ["cam"]
