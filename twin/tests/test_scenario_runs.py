"""One trigger, one log: a Test Book scenario through the real clock and API, with mock partners in process."""
import asyncio

import httpx
import pytest

from conftest import ALL_TYPES, load_mock
from twin.city.two_blocks import TwoBlocksCity
from twin.config import Settings
from twin.main import create_app
from twin.testbook import SCENARIOS

HMAC, BRAIN_KEY, GUARDIAN_KEY, OPERATOR = "h", "brain-key", "guardian-key", "op"
H = {"X-Operator-Key": OPERATOR}


class Router(httpx.AsyncBaseTransport):
    def __init__(self, apps):
        self.transports = {host: httpx.ASGITransport(app=app) for host, app in apps.items()}

    async def handle_async_request(self, request):
        if request.url.host not in self.transports:
            raise httpx.ConnectError(f"{request.url.host} is down")
        return await self.transports[request.url.host].handle_async_request(request)


def _world(monkeypatch, tmp_path, partners=("guardian", "brain"), scenario="ped-hit"):
    monkeypatch.setenv("TWIN_HMAC_KEY", HMAC)
    monkeypatch.setenv("TWIN_BRAIN_API_KEY", BRAIN_KEY)
    monkeypatch.setenv("TWIN_URL", "http://twin:8000")
    monkeypatch.setenv("GUARDIAN_URL", "http://guardian:8001")
    guardian, brain = load_mock("guardian", "run_guardian"), load_mock("brain", "run_brain")
    twin = create_app(Settings(hmac_key=HMAC, brain_api_key=BRAIN_KEY, guardian_api_key=GUARDIAN_KEY, operator_key=OPERATOR,
                               emit_interval_s=0.05, log_dir=str(tmp_path), guardian_url="http://guardian:8001", brain_url="http://brain:8002",
                               guardian_ingest_url="http://guardian:8001/v1/readings", guardian_extended_types=ALL_TYPES),
                      TwoBlocksCity(scenario))
    apps = {"twin": twin}
    if "guardian" in partners:
        apps["guardian"] = guardian.app
    if "brain" in partners:
        apps["brain"] = brain.app
    router = Router(apps)
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(**{"transport": router, **kw}))
    return twin, brain


async def _run_until_done(twin, brain, scenario_id, body):
    """The app's background loops, sped up: the clock at 8x would take a minute, so tick the engine directly."""
    emitter, live = twin.state.emitter, twin.state.live
    async with httpx.AsyncClient() as client:
        emitter.client = client
        started = await client.post(f"http://twin:8000/scenarios/{scenario_id}/run", json=body, headers=H)
        assert started.status_code == 202, started.text
        again = await client.post(f"http://twin:8000/scenarios/{scenario_id}/run", json=body, headers=H)
        assert again.status_code == 409
        runs = twin.state.runs
        for _ in range(60_000):
            if runs.current is None:
                break
            for _ in range(10):
                live.tick()
            await emitter.tick()
            if brain is not None and (await client.get("http://brain:8002/health")).status_code == 200:
                await brain.desk.poll_once(client)
            await asyncio.sleep(0)
        return runs.last


@pytest.mark.parametrize("scenario_id", sorted(SCENARIOS))
def test_a_scenario_ends_with_a_pass_and_one_log_file(monkeypatch, tmp_path, scenario_id):
    twin, brain = _world(monkeypatch, tmp_path)
    last = asyncio.run(_run_until_done(twin, brain, scenario_id, {"speed": 8}))
    assert last["result"] == "PASS", [c for c in last["checks"] if not c["seen"]]
    logs = list(tmp_path.glob(f"{scenario_id}-*.log"))
    assert [p.name for p in logs] == [last["log"]]
    text = logs[0].read_text()
    assert text.rstrip().endswith("# result: PASS")
    for layer in ("twin", "guardian", "city_brain"):
        assert f" {layer} " in text
    assert "reading_emitted" not in text


def test_a_partner_being_down_is_reported_and_the_run_still_logs(monkeypatch, tmp_path):
    twin, _ = _world(monkeypatch, tmp_path, partners=("guardian",))
    twin.state.runs.live.city.reset("ped-hit")

    async def scenario():
        async with httpx.AsyncClient() as client:
            for _ in range(5):
                twin.state.live.tick()
            return await client.get("http://twin:8000/timeline", headers=H)

    body = asyncio.run(scenario()).json()
    assert body["layers"]["guardian"]["reachable"] is True
    assert body["layers"]["city_brain"]["reachable"] is False and body["layers"]["city_brain"]["error"]


@pytest.mark.parametrize("method,path,body", [("get", "/timeline", None), ("get", "/scenarios", None),
                                              ("post", "/scenarios/t1/run", {}), ("post", "/live/control", {"action": "pause"})])
def test_operator_endpoints_need_the_operator_key(monkeypatch, tmp_path, method, path, body):
    twin, _ = _world(monkeypatch, tmp_path)

    async def scenario():
        async with httpx.AsyncClient() as client:
            return await client.request(method, f"http://twin:8000{path}", json=body)

    assert asyncio.run(scenario()).status_code == 401


@pytest.mark.parametrize("body,code", [({"speed": 99}, 422), ({"brain": "nobody"}, 422), ({"seed": "x"}, 422)])
def test_a_bad_run_request_is_refused_clearly(monkeypatch, tmp_path, body, code):
    twin, _ = _world(monkeypatch, tmp_path)

    async def scenario():
        async with httpx.AsyncClient() as client:
            return await client.post("http://twin:8000/scenarios/t1/run", json=body, headers=H)

    resp = asyncio.run(scenario())
    assert resp.status_code == code and resp.json()["detail"]


def test_unknown_scenario_lists_the_known_ones(monkeypatch, tmp_path):
    twin, _ = _world(monkeypatch, tmp_path)

    async def scenario():
        async with httpx.AsyncClient() as client:
            return await client.post("http://twin:8000/scenarios/t9/run", json={}, headers=H)

    resp = asyncio.run(scenario())
    assert resp.status_code == 404 and "t1" in resp.json()["detail"]


def test_city_params_can_change_at_a_new_run_and_bad_ones_are_clear(monkeypatch, tmp_path):
    twin, _ = _world(monkeypatch, tmp_path, scenario="city")

    async def scenario():
        async with httpx.AsyncClient() as client:
            ok = await client.post("http://twin:8000/live/control", headers=H, json={
                "action": "load", "scenario": "city", "params": {"cars": 8, "pedestrians": 12, "car_crash_risk": 0.5, "ped_hit_risk": 0.0}})
            bad = await client.post("http://twin:8000/live/control", headers=H, json={"action": "reset", "params": {"cars": 99}})
            return ok, bad

    ok, bad = asyncio.run(scenario())
    assert ok.json()["params"] == {"cars": 8, "pedestrians": 12, "car_crash_risk": 0.5, "ped_hit_risk": 0.0, "fire_risk": 0.0,
                                  "flood_risk": 0.0}
    assert len([c for c in twin.state.city.sim.cars.values() if c.id.startswith("car")]) == 8
    assert bad.status_code == 422 and "cars" in bad.json()["detail"]
