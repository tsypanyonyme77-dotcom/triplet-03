"""Live mode: the clock streams frames and resets; the live endpoints; the Brain's incident desk
reading the Guardian's history and acting only when told."""
import asyncio
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from twin.city.two_blocks import TwoBlocksCity
from twin.config import Settings
from twin.events import EventLog
from twin.live import MAX_FAILED_TICKS, LiveRunner
from twin.main import create_app

KEY = "k"


def test_the_live_clock_streams_frames_and_a_reset_starts_a_new_run():
    async def scenario():
        city = TwoBlocksCity("ped-hit")
        runner = LiveRunner(city, EventLog("twin"), speed=8.0)
        queue = runner.subscribe()
        task = asyncio.create_task(runner.run())
        await asyncio.sleep(0.6)  # about 48 ticks at 8x
        frames = []
        while not queue.empty():
            frames.append(queue.get_nowait())
        t_before = city.sim_time
        status = await runner.control("load", scenario="car-crash")
        await asyncio.sleep(0.05)
        task.cancel()
        msgs = []
        while not queue.empty():
            msgs.append(queue.get_nowait())
        return frames, t_before, status, msgs

    frames, t_before, status, msgs = asyncio.run(scenario())
    assert len(frames) >= 20 and all(m.startswith("event: frame\n") for m in frames)
    first = json.loads(frames[0].split("data: ", 1)[1])
    assert set(first) >= {"t", "cars", "pedestrians", "lights", "accidents", "calls"}   # the recording frame format
    ts = [json.loads(m.split("data: ", 1)[1])["t"] for m in frames]
    assert ts == sorted(ts) and t_before >= 2.0
    assert status["run_id"] == 2 and status["scenario"] == "car-crash" and status["sim_time_s"] < 1.0
    assert msgs[0].startswith("event: reset\n")


def test_live_endpoints_answer_and_are_off_without_live_mode():
    city = TwoBlocksCity("ped-hit")
    client = TestClient(create_app(Settings(live=True, emit_enabled=False, brain_api_key=KEY), city))
    m = client.get("/live/map").json()
    assert m["dt"] == 0.1 and {"roads", "parking", "stations"} <= set(m["map"]) and m["scenario"] == "ped-hit"
    assert client.get("/live/status").json()["run_id"] == 1
    units = {u["unit_id"]: u for u in client.get("/units").json()["units"]}
    assert set(units) == {"amb1", "police1", "fire1"} and all(u["status"] == "idle" for u in units.values())
    assert client.get("/responses").json()["responses"] == []
    assert client.post("/live/control", json={"action": "fly"}).status_code == 422
    off = TestClient(create_app(Settings(live=False, emit_enabled=False), TwoBlocksCity("ped-hit")))
    assert off.get("/live/status").status_code == 404 and off.get("/stream/frames").status_code == 404


class _Router(httpx.AsyncBaseTransport):
    """One HTTP client for the Brain that reaches the in-process Twin (port 8000) and Guardian (8001)."""

    def __init__(self, apps):
        self.apps = {port: httpx.ASGITransport(app=app) for port, app in apps.items()}

    async def handle_async_request(self, request):
        return await self.apps[request.url.port].handle_async_request(request)


def test_the_brain_lists_incidents_from_guardian_history_and_dispatches_only_when_told(guardian_mock):
    from conftest import ALL_TYPES, load_mock, send_to_guardian
    from twin.partners.guardian_dialect import GuardianDialect

    brain = load_mock("brain", "mock_brain_live")
    city = TwoBlocksCity("ped-hit")
    twin_app = create_app(Settings(live=True, emit_enabled=False, brain_api_key=KEY, guardian_extended_types=ALL_TYPES,
                                   guardian_ingest_url="http://guardian:8001/v1/readings"), city)
    brain.TWIN_URL, brain.GUARDIAN_URL, brain.TWIN_API_KEY = "http://twin:8000", "http://guardian:8001", KEY
    emitter = twin_app.state.emitter
    guardian = TestClient(guardian_mock.app)
    dialect = GuardianDialect(twin_app.state.emitter.settings.hmac_key, ALL_TYPES)

    async def scenario():
        async with httpx.AsyncClient(transport=_Router({8000: twin_app, 8001: guardian_mock.app})) as client:
            desk = brain.desk
            for _ in range(65):                       # 65 s: the hit at 48.7 s, camera and calls
                city.step(1.0)
                for r in await emitter.tick():
                    send_to_guardian(guardian, r, dialect)
                await desk.poll_once(client)
            listed = [dict(i) for i in desk.board.list()]
            moved_before = [u for u in city.sim.units.values() if u.status != "idle"]
            entry = await desk.send(client, "dispatch_ambulance", brain.rules.build_call(listed[0], "dispatch_ambulance"))
            again = await desk.send(client, "dispatch_ambulance", brain.rules.build_call(listed[0], "dispatch_ambulance"))
            await desk.poll_once(client)
            status_after = desk.board.incidents[listed[0]["incident_id"]]["status"]
            dispatched = sum(e["kind"] == "unit_dispatched" for e in city.sim.timeline)
            city.reset("car-crash")
            await desk.poll_once(client)
            return listed, moved_before, entry, again, status_after, dispatched, desk.board.list(), desk.run_id

    listed, moved_before, entry, again, status_after, dispatched, after_reset, run_id = asyncio.run(scenario())
    assert [i["incident_id"] for i in listed] == ["inc-0001"] and listed[0]["status"] == "reported"
    assert "camera" in listed[0]["sources"] and listed[0]["trust_ref"].startswith("verdict-")
    assert moved_before == []                                            # manual: nothing moved on its own
    assert entry["result"]["status"] == "dispatched" and again["result"]["status"] == "duplicate"
    assert entry["call"]["requesting_layer"] == "city_brain" and entry["call"]["idempotency_key"]
    assert dispatched == 1
    assert status_after == "unit_dispatched"
    assert after_reset == [] and run_id == 2                             # a new Twin run clears the board


def _strict(text: str):
    """JSON as a browser parses it: NaN or Infinity in a frame would kill the viewer's stream."""
    def refuse(token):
        raise ValueError(f"{token} in a frame")
    return json.loads(text, parse_constant=refuse)


@pytest.mark.parametrize("scenario", ["ped-hit", "car-crash"])
def test_the_live_clock_survives_a_whole_incident_with_dispatches(scenario):
    """The real clock (LiveRunner.run, at 100x), the real API, 300 simulated seconds in 3 real ones:
    a crash, a stall or an unparsable frame anywhere in a run shows up here, not on stage."""
    city = TwoBlocksCity(scenario)
    app = create_app(Settings(live=True, emit_enabled=False, brain_api_key=KEY), city)
    runner, emitter, events = app.state.live, app.state.emitter, app.state.events
    runner.speed = 100.0  # flat out it would outrun the API's thread pool and overflow the frame queue
    queue = runner.subscribe()
    seen = {"frames": 0, "last_t": 0.0, "answers": {}, "slowest": 0.0, "logged": set()}

    def drain():
        while not queue.empty():
            message = queue.get_nowait()
            assert message.startswith("event: frame\n")
            frame = _strict(message.split("data: ", 1)[1])
            assert frame["t"] > seen["last_t"], "frame times must go forward"
            seen["last_t"], seen["frames"] = frame["t"], seen["frames"] + 1

    async def dispatch(client, unit_type, incident_id):
        call = {"contract_version": "2026-09-17", "actuator_id": "dispatch-centre-01", "action": "dispatch_unit",
                "params": {"unit_type": unit_type, "incident_id": incident_id}, "requesting_layer": "city_brain",
                "justification": "long run test", "trust_ref": "verdict-test"}
        resp = await client.post("/actuators/call", json=call, headers={"X-Api-Key": KEY})
        assert resp.status_code == 200, resp.text
        return resp.json()["result"]["status"]

    async def run():
        task = asyncio.create_task(runner.run())
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://twin") as client:
            next_exchange, incident = 1.0, None
            while city.sim_time < 300.0:
                await asyncio.sleep(0)
                drain()
                if city.sim_time < next_exchange:
                    continue
                next_exchange += 1.0
                started = time.perf_counter()
                await emitter.tick()   # what the emitter does every second: every reading signed
                for path in ("/live/status", "/units", "/responses", "/events?limit=50", "/health"):
                    assert (await client.get(path)).status_code == 200, path
                seen["slowest"] = max(seen["slowest"], time.perf_counter() - started)
                seen["logged"] |= {e["kind"] for e in events.recent(1000)}
                if incident is None:
                    incident = next((r["value"]["incident_id"] for r in emitter.latest.values()
                                     if r["value"].get("incident_id")), None)
                    if incident:
                        seen["answers"]["ambulance"] = await dispatch(client, "ambulance", incident)
                        seen["answers"]["police"] = await dispatch(client, "police", incident)
                        seen["answers"]["again"] = await dispatch(client, "ambulance", incident)
            drain()
            after = (await client.post("/live/control", json={"action": "load", "scenario": "city"})).json()
            task.cancel()
            return after, incident

    after, incident = asyncio.run(run())
    assert not seen["logged"] & {"live_tick_error", "live_engine_stopped", "tick_error"}
    assert runner.engine_error is None
    assert seen["frames"] >= 2990                                 # 300 s at 10 Hz, none lost or out of order
    assert incident is not None
    assert seen["answers"] == {"ambulance": "dispatched", "police": "dispatched", "again": "duplicate"}
    assert {"sim_incident", "unit_dispatched", "sim_unit_pulled_out", "sim_crew_out"} <= seen["logged"]
    assert after["run_id"] == 2 and after["scenario"] == "city"
    assert seen["slowest"] < 0.5                                  # the API stays responsive between ticks


class _BrokenCity:
    """A city whose engine raises once `broken` is set; `reset` repairs it."""
    dt, run_id, scenario_name, seed, sim_time, SCENARIOS = 0.1, 1, "city", None, 0.0, ("city",)

    def __init__(self):
        self.broken, self.steps = False, 0

    def params_dict(self):
        return {}

    def step(self, _dt):
        self.steps += 1
        if self.broken:
            raise RuntimeError("the engine broke")
        return []

    def frame(self):
        return {"t": self.steps * self.dt}

    def reset(self, _scenario=None, _seed=None, _params=None):
        self.broken, self.run_id = False, self.run_id + 1


def test_a_failing_engine_is_logged_once_stops_and_a_reset_restarts_it(caplog):
    city = _BrokenCity()
    log = EventLog("twin")
    runner = LiveRunner(city, log)
    runner.tick()
    assert runner.engine_error is None

    city.broken = True
    for _ in range(MAX_FAILED_TICKS - 1):
        runner.tick()
    assert runner.engine_error is None                                     # might still recover
    assert sum(e["kind"] == "live_tick_error" for e in log.recent()) == 1  # not one per tick
    assert "the engine broke" in caplog.text and "Traceback" in caplog.text
    runner.tick()
    assert "the engine broke" in runner.status()["engine_error"]
    assert sum(e["kind"] == "live_engine_stopped" for e in log.recent()) == 1

    async def clock_holds_then_restarts():
        task = asyncio.create_task(runner.run())
        await asyncio.sleep(0.05)
        held = city.steps
        await asyncio.sleep(0.15)
        assert city.steps == held                                          # stopped: no more ticks
        status = await runner.control("reset")
        await asyncio.sleep(0.15)
        task.cancel()
        return status, held

    status, held = asyncio.run(clock_holds_then_restarts())
    assert status["engine_error"] is None and status["run_id"] == 2 and city.steps > held


def test_a_broken_engine_leaves_the_http_api_up():
    city = TwoBlocksCity("ped-hit")
    app = create_app(Settings(live=True, emit_enabled=False, brain_api_key=KEY), city)
    city.step = lambda _dt: 1 / 0
    for _ in range(MAX_FAILED_TICKS):
        app.state.live.tick()
    client = TestClient(app)
    health = client.get("/health").json()
    assert health["status"] == "degraded" and "division by zero" in health["engine_error"]
    assert "division by zero" in client.get("/live/status").json()["engine_error"]
    assert client.get("/live/map").status_code == 200 and client.get("/units").status_code == 200


def test_an_unwritable_event_log_does_not_stop_anything(tmp_path, caplog):
    log = EventLog("twin", str(tmp_path))
    (tmp_path / "twin.ndjson").mkdir()                 # opening it for append now raises OSError
    log.emit("a", "first")
    log.emit("b", "second")
    assert [e["kind"] for e in log.recent()] == ["a", "b"]
    assert caplog.text.count("cannot write") == 1


def test_a_stream_says_hello_with_the_instance_and_pings_when_quiet():
    async def scenario():
        runner = LiveRunner(TwoBlocksCity("ped-hit"), EventLog("twin"))
        stream = runner.stream(ping_s=0.01)
        hello = await anext(stream)
        ping = await anext(stream)
        runner.tick()
        frame = await anext(stream)
        await stream.aclose()
        return runner, hello, ping, frame

    runner, hello, ping, frame = asyncio.run(scenario())
    assert hello.startswith("event: hello\n")
    assert _strict(hello.split("data: ", 1)[1])["instance"] == runner.instance
    assert ping.startswith("event: ping\n") and frame.startswith("event: frame\n")
    assert not runner._subscribers                     # a client that left is forgotten


def test_the_live_agents_route_lists_everyone_with_profile_and_destination():
    city = TwoBlocksCity("city", seed=1, decision="student")
    for _ in range(3):
        city.step(0.1)
    client = TestClient(create_app(Settings(live=True, emit_enabled=False), city))
    body = client.get("/live/agents").json()
    assert body["run_id"] == 1 and len(body["agents"]) == 60
    a = body["agents"][0]
    assert a["destination"]["name"] and a["traits"]["urgency"] >= 0 and a["role"]
    # without the decision model there is nobody to describe, and the route still answers
    plain = TestClient(create_app(Settings(live=True, emit_enabled=False), TwoBlocksCity("city", seed=1)))
    assert plain.get("/live/agents").json()["agents"] == []
    assert TestClient(create_app(Settings(live=False, emit_enabled=False), TwoBlocksCity("city"))).get("/live/agents").status_code == 404
