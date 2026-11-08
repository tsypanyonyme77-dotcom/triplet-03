"""A whole incident in one process: Twin -> Guardian mock -> City Brain mock -> Twin actuator.

httpx calls between the three apps are routed in memory by hostname, so no ports or Docker are needed.
"""
import asyncio

import httpx
import pytest

from conftest import load_mock
from twin.city.two_blocks import TwoBlocksCity
from twin.config import Settings
from twin.main import create_app

HMAC, API_KEY = "e2e-hmac", "e2e-key"


class Router(httpx.AsyncBaseTransport):
    def __init__(self, apps):
        self.transports = {host: httpx.ASGITransport(app=app) for host, app in apps.items()}

    async def handle_async_request(self, request):
        return await self.transports[request.url.host].handle_async_request(request)


@pytest.fixture
def world(monkeypatch):
    monkeypatch.setenv("TWIN_HMAC_KEY", HMAC)
    monkeypatch.setenv("TWIN_API_KEY", API_KEY)
    monkeypatch.setenv("TWIN_URL", "http://twin:8000")
    monkeypatch.setenv("GUARDIAN_URL", "http://guardian:8001")
    guardian = load_mock("guardian", "e2e_guardian")
    brain = load_mock("brain", "e2e_brain")
    city = TwoBlocksCity("ped-hit")
    city.step(60.0)  # the accident has happened and been called in
    twin = create_app(Settings(emit_enabled=False, hmac_key=HMAC, brain_api_key=API_KEY,
                               guardian_ingest_url="http://guardian:8001/ingest", brain_notify_url="http://brain:8002/notify"), city)
    router = Router({"twin": twin, "guardian": guardian.app, "brain": brain.app})
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(**{"transport": router, **kw}))
    return twin, guardian, brain, router


async def _report_incident(twin, brain, client) -> str:
    twin.state.emitter.client = client
    await twin.state.emitter.tick()  # readings go to the Guardian, the Brain is pinged
    await brain.desk.poll_once(client)  # the Brain reads what the Guardian verified
    incidents = (await client.get("http://brain:8002/api/incidents")).json()["incidents"]
    assert len(incidents) == 1
    return incidents[0]["incident_id"]


def test_an_incident_end_to_end(world):
    twin, guardian, brain, router = world

    async def scenario():
        async with httpx.AsyncClient() as client:
            incident = await _report_incident(twin, brain, client)
            url = f"http://brain:8002/api/incidents/{incident}/actions"
            first = (await client.post(url, json={"action": "dispatch_ambulance"})).json()
            again = (await client.post(url, json={"action": "dispatch_ambulance"})).json()
            seen = []
            for host in ("twin:8000", "guardian:8001", "brain:8002"):
                seen += [(e["layer"], e["kind"]) for e in (await client.get(f"http://{host}/events", params={"limit": 1000})).json()["events"]]
            return first, again, seen

    first, again, seen = asyncio.run(scenario())
    assert first["result"]["status"] == "dispatched"
    assert again["result"]["status"] in ("duplicate", "dispatched")  # the mock's idempotency key may replay the first answer
    for expected in [("twin", "reading_emitted"), ("twin", "brain_notified"), ("guardian", "readings_verified"), ("guardian", "verdict_issued"),
                     ("city_brain", "notified"), ("city_brain", "incident_reported"), ("twin", "actuator_call_received"),
                     ("twin", "unit_dispatched"), ("city_brain", "actuator_called")]:
        assert expected in seen, f"missing {expected} in {seen}"


def test_brain_without_valid_key_is_refused_by_twin(world, monkeypatch):
    twin, guardian, brain, router = world
    monkeypatch.setattr(brain, "TWIN_API_KEY", "wrong")

    async def scenario():
        async with httpx.AsyncClient() as client:
            incident = await _report_incident(twin, brain, client)
            return (await client.post(f"http://brain:8002/api/incidents/{incident}/actions", json={"action": "dispatch_ambulance"})).json()

    assert asyncio.run(scenario())["http"] == 401


def test_twin_survives_partner_down():
    down = create_app(Settings(emit_enabled=False, live=False, guardian_ingest_url="http://nowhere:1/ingest",
                               brain_notify_url="http://nowhere:1/notify"))

    class Dead(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request):
            raise httpx.ConnectError("refused")

    async def scenario():
        async with httpx.AsyncClient(transport=Dead()) as client:
            down.state.emitter.client = client
            return await down.state.emitter.tick()

    assert asyncio.run(scenario())  # the readings are still built and kept
    kinds = [e["kind"] for e in down.state.events.recent()]
    assert kinds.count("delivery_failed") == 2
