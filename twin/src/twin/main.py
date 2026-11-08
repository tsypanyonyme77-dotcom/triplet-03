"""Twin layer HTTP API (microservice).

Read side : GET /zones, GET /sensors, GET /stream/readings (SSE), GET /events, GET /units, GET /responses
Write side: GET /actuators, POST /actuators/call
Push side : the emitter pushes signed readings to the Guardian (see emitter.py).
Partners  : the City Brain's carriers, GET /readings, GET /topology, GET /capabilities, POST /actuators/{action},
            and the same as MCP tools at /mcp; the Guardian's POST /tools/{action} (see twin/partners/).
Viewer    : GET /live/status, GET /live/map, GET /live/agents, GET /stream/frames (SSE)
Operator  : POST /live/control, POST /scenarios/{id}/run, GET /scenarios, GET /scenarios/runs[/{n}],
            GET /timeline (ground truth included),
            POST /simulators/ignite_fire (set a building on fire)
            POST /simulators/flood_street (block a street's drain and bring a downpour over it)
"""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from twin.actuation import Actuation, CallRefused
from twin.actuators import describe
from twin.city.base import CitySource
from twin.city.two_blocks import TwoBlocksCity
from twin.config import Settings
from twin.contract import CONTRACT_VERSION, ActuatorCall
from twin.devices import DeviceRegistry
from twin.emitter import Emitter
from twin.events import EventLog
from twin.live import LiveRunner
from twin.partners.brain_calls import BrainDoor
from twin.partners.brain_http import brain_router
from twin.partners.brain_mcp import brain_mcp_server, mcp_app
from twin.partners.brain_timeline import BrainTimeline
from twin.partners.guardian_dialect import GuardianDialect
from twin.partners.guardian_push import GuardianPush
from twin.partners.guardian_tools import GuardianDoor, guardian_router
from twin.partners.incident_links import IncidentLinks
from twin.partners.reading_log import ReadingLog
from twin.scenario_runs import DEFAULT_SPEED, ScenarioBusy, ScenarioRunner
from twin.testbook import SCENARIOS
from twin.timeline import collect
from twin.world.scenarios import CityParams

log = logging.getLogger("twin.main")


def make_city(settings: Settings) -> CitySource:
    params = CityParams(settings.cars, settings.pedestrians, settings.car_crash_risk, settings.ped_hit_risk, settings.fire_risk,
                        settings.flood_risk)
    return TwoBlocksCity(settings.scenario, settings.seed, params, decision=settings.decision)


def create_app(settings: Settings | None = None, city: CitySource | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    city = city or make_city(settings)
    events = EventLog("twin", settings.log_dir)
    live = LiveRunner(city, events, settings.live_speed) if settings.live else None
    devices = DeviceRegistry()
    links = IncidentLinks(city)
    reading_log = ReadingLog()
    guardian_push = (GuardianPush(settings.guardian_ingest_url, settings.guardian_push_api_key, GuardianDialect(settings.hmac_key, settings.guardian_extended_types), events)
                     if settings.guardian_dialect == "guardian-v1" else None)
    brain_timeline = BrainTimeline(settings.brain_events_url, settings.brain_push_token, events) if settings.brain_events_url else None
    emitter = Emitter(settings, city, events, step_city=live is None, devices=devices, log=reading_log, guardian=guardian_push,
                      view=links.partner_view, timeline=brain_timeline)
    partners = {"guardian": settings.guardian_url, "city_brain": settings.brain_url}
    actuation = Actuation(city, devices, events)
    brain_door = BrainDoor(actuation, city, links, events, hmac_secret=settings.brain_hmac_secret, api_key=settings.brain_api_key)
    guardian_door = GuardianDoor(actuation, city, links, events, api_key=settings.tools_api_key)
    mcp_server = brain_mcp_server(reading_log, city, brain_door)
    mcp_asgi = mcp_app(mcp_server, list(settings.mcp_allowed_hosts))   # creates the session manager the lifespan runs

    def new_run() -> None:
        actuation.new_run()
        devices.clear_all()
        links.clear()

    runs = ScenarioRunner(live, events, partners, settings.log_dir, new_run) if live is not None else None
    layer_keys = {"city_brain": settings.brain_api_key, "guardian": settings.guardian_api_key}
    auth_on = any(layer_keys.values())

    def require_operator(key: str | None) -> None:
        if settings.operator_key and key != settings.operator_key:
            raise HTTPException(401, "missing or invalid X-Operator-Key header")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        def report_if_crashed(task: asyncio.Task) -> None:
            # both loops contain their ticks' failures, so this would be a bug in a loop itself:
            # without it the task dies in silence while the API goes on answering with frozen data
            if not task.cancelled() and task.exception() is not None:
                log.error("background task %s died", task.get_name(), exc_info=task.exception())
                events.emit("background_task_died", f"{task.get_name()} died: {task.exception()!r}", task=task.get_name())

        tasks = [asyncio.create_task(emitter.run(), name="emitter")] if settings.emit_enabled else []
        if live is not None:
            tasks.append(asyncio.create_task(live.run(), name="live clock"))
        for task in tasks:
            task.add_done_callback(report_if_crashed)
        events.emit("startup", f"twin up (scenario={settings.scenario}, interval={settings.emit_interval_s}s)")
        async with mcp_server.session_manager.run():   # the MCP endpoint's sessions (/mcp)
            yield
        for task in tasks:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    app = FastAPI(title="Twin Layer", version="0.1.0", lifespan=lifespan)
    app.state.emitter, app.state.events, app.state.city, app.state.live, app.state.runs = emitter, events, city, live, runs
    app.state.actuation, app.state.links, app.state.reading_log = actuation, links, reading_log
    app.state.mcp_server = mcp_server

    @app.get("/health")
    def health():
        engine_error = live.engine_error if live is not None else None
        return {"status": "degraded" if engine_error else "ok", "contract_version": CONTRACT_VERSION,
                "engine_error": engine_error}

    @app.get("/zones")
    def zones():
        return {"contract_version": CONTRACT_VERSION, "zones": city.zones()}

    @app.get("/sensors")
    def sensor_readings():
        """The latest signed reading of every sensor (emergency calls, cameras)."""
        return {"contract_version": CONTRACT_VERSION, "readings": list(emitter.latest.values())}

    # ---- the real-time clock: the 3D viewer's data ----------------

    def _need_live() -> LiveRunner:
        if live is None:
            raise HTTPException(404, "the real-time clock is off")
        return live

    @app.get("/live/status")
    def live_status():
        return {**_need_live().status(), "contract_version": CONTRACT_VERSION}

    @app.get("/live/map")
    def live_map():
        """The map section of a recording (roads, parking, walkways, stations) for the current run."""
        runner = _need_live()
        return {**city.map(), "instance": runner.instance, "run_id": city.run_id, "scenario": city.scenario_name}

    @app.get("/live/agents")
    async def live_agents():
        """Each pedestrian and driver: profile and traits, where they stand, where they are heading and why.
        `async` on purpose: it runs between clock ticks, never in the middle of one."""
        runner = _need_live()
        agents = city.agents() if hasattr(city, "agents") else []
        return {"agents": agents, "run_id": city.run_id, "sim_time_s": city.sim_time, "instance": runner.instance}

    @app.get("/stream/frames")
    async def stream_frames():
        """Server-sent events: `frame` every tick (recording frame format), `reset` when a new run starts."""
        return StreamingResponse(_need_live().stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

    @app.post("/live/control")
    async def live_control(body: dict, x_operator_key: str | None = Header(default=None)):
        """Demo control: {"action": "pause" | "resume" | "reset" | "load" | "speed", "scenario"?, "seed"?, "speed"?,
        "params"?: {"cars", "pedestrians", "car_crash_risk", "ped_hit_risk", "fire_risk", "flood_risk"}}."""
        require_operator(x_operator_key)
        runner = _need_live()
        action = body.get("action", "")
        try:
            params = CityParams(**body["params"]) if body.get("params") is not None else None
            status = await runner.control(action, body.get("scenario"), body.get("seed"), body.get("speed"), params)
        except (ValueError, TypeError) as exc:
            raise HTTPException(422, str(exc))
        if action in ("reset", "load"):
            new_run()
        return status

    # ---- the Test Book's scenarios and the live timeline ---------------------------------------

    @app.get("/scenarios")
    def list_scenarios(x_operator_key: str | None = Header(default=None)):
        require_operator(x_operator_key)
        if runs is None:
            raise HTTPException(404, "the real-time clock is off")
        return runs.status()

    @app.get("/scenarios/runs")
    def scenario_runs(x_operator_key: str | None = Header(default=None)):
        """Finished scenario runs, newest first: number, scenario, result, log, when."""
        require_operator(x_operator_key)
        if runs is None:
            raise HTTPException(404, "the real-time clock is off")
        return {"runs": runs.runs()}

    @app.get("/scenarios/runs/{number}")
    def scenario_run(number: int, x_operator_key: str | None = Header(default=None)):
        """One finished run with every event of the three layers, routine ones flagged: its timeline."""
        require_operator(x_operator_key)
        if runs is None:
            raise HTTPException(404, "the real-time clock is off")
        found = runs.run(number)
        if found is None:
            raise HTTPException(404, f"no finished run {number}; the last {len(runs.history)} are kept")
        return found

    @app.post("/scenarios/{scenario_id}/run", status_code=202)
    async def run_scenario(scenario_id: str, body: dict | None = None, x_operator_key: str | None = Header(default=None)):
        """One trigger, one log file. Body (all optional): {"seed", "speed", "brain": "auto" | "operator"}."""
        require_operator(x_operator_key)
        if runs is None:
            raise HTTPException(404, "the real-time clock is off")
        if scenario_id not in SCENARIOS:
            raise HTTPException(404, f"unknown scenario '{scenario_id}', known scenarios: {sorted(SCENARIOS)}")
        body = body or {}
        speed, brain, seed = body.get("speed", DEFAULT_SPEED), body.get("brain", "auto"), body.get("seed")
        if not isinstance(speed, (int, float)) or isinstance(speed, bool) or not 0.1 <= speed <= 8.0:
            raise HTTPException(422, "speed must be a number between 0.1 and 8")
        if brain not in ("auto", "operator"):
            raise HTTPException(422, "brain must be 'auto' or 'operator'")
        if seed is not None and (not isinstance(seed, int) or isinstance(seed, bool)):
            raise HTTPException(422, "seed must be an integer")
        try:
            return runs.start(scenario_id, seed, float(speed), brain)
        except ScenarioBusy as exc:
            raise HTTPException(409, str(exc))

    @app.post("/simulators/ignite_fire")
    async def ignite_fire(body: dict, x_operator_key: str | None = Header(default=None)):
        """The fire simulator: set a building on fire, `{"building_id": "bld-01-03"}` (ids are in the viewer's map).
        Idempotent: a building already burning answers `duplicate` with its fire. The other layers learn of the
        fire only as sensors and callers report it. Operator key, like the other controls."""
        require_operator(x_operator_key)
        building_id = body.get("building_id")
        if not isinstance(building_id, str) or not building_id:
            raise HTTPException(422, "building_id must be a non-empty string, e.g. 'bld-01-03'")
        if not hasattr(city, "ignite_fire"):
            raise HTTPException(404, "this city has no buildings that can burn")
        result = city.ignite_fire(building_id)
        if result["status"] == "rejected":
            raise HTTPException(404, f"unknown building '{building_id}'")
        return {"contract_version": CONTRACT_VERSION, "run_id": getattr(city, "run_id", None), **result}

    @app.post("/simulators/flood_street")
    async def flood_street(body: dict, x_operator_key: str | None = Header(default=None)):
        """The flood simulator: block the storm drain of a street and bring a downpour over it,
        `{"zone_id": "dip-1-2"}` (one per street; ids are in the viewer's map and GET /flood). Idempotent: a
        street already under its downpour answers `duplicate`. The other layers learn of it from the rain
        gauge and water level of that street, and from callers. Operator key, like the other controls."""
        require_operator(x_operator_key)
        zone_id = body.get("zone_id")
        if not isinstance(zone_id, str) or not zone_id:
            raise HTTPException(422, "zone_id must be a non-empty string, e.g. 'dip-1-2'")
        result = city.flood_street(zone_id)
        if result["status"] == "rejected":
            raise HTTPException(404, f"unknown flood zone '{zone_id}'")
        return {"contract_version": CONTRACT_VERSION, "run_id": getattr(city, "run_id", None), **result}

    @app.get("/flood")
    def flood():
        """Every street's flood zone: water depth, rain, drain and pump."""
        return {"contract_version": CONTRACT_VERSION, "zones": city.flood_state()}

    @app.get("/timeline")
    async def timeline(since: str = "", limit: int = 500, routine: bool = False, x_operator_key: str | None = Header(default=None)):
        """All three layers, merged by time, with the engine's ground truth: an operator's view (R3). With
        `routine=true`, the periodic readings and notifications too, flagged `routine`."""
        require_operator(x_operator_key)
        return await collect(events, partners, since, limit, routine)

    @app.get("/units")
    def units():
        """Emergency units: type, station, status, incident, ETA ."""
        if not hasattr(city, "units"):
            return {"contract_version": CONTRACT_VERSION, "units": []}
        return {"contract_version": CONTRACT_VERSION, "sim_time_s": getattr(city, "sim_time", None), "units": city.units()}

    @app.get("/responses")
    def responses():
        """Actuator feedback per incident: what the Twin's units are doing (phase, units sent, road closed)."""
        if not hasattr(city, "responses"):
            return {"contract_version": CONTRACT_VERSION, "responses": []}
        return {"contract_version": CONTRACT_VERSION, "run_id": getattr(city, "run_id", None), "responses": city.responses()}

    @app.get("/stream/readings")
    async def stream_readings():
        """Server-sent events: every reading as it is emitted."""
        queue = emitter.subscribe()

        async def gen():
            try:
                while True:
                    reading = await queue.get()
                    yield f"event: reading\ndata: {json.dumps(reading)}\n\n"
            finally:
                emitter.unsubscribe(queue)

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.get("/events")
    def get_events(limit: int = 200):
        """What happened in this layer, for the other layers: no ground truth."""
        return {"events": events.public(limit)}

    @app.get("/quarantine")
    def quarantine():
        return {"contract_version": CONTRACT_VERSION, "devices": devices.list()}

    @app.get("/actuators")
    def list_actuators():
        """The actuator catalog the City Brain (and Guardian) read: actions, ids, JSON Schemas, availability."""
        return {"contract_version": CONTRACT_VERSION, "actuators": describe()}

    @app.post("/actuators/call")
    async def actuator_call(call: ActuatorCall, x_api_key: str | None = Header(default=None)):
        # async on purpose: runs on the event loop, so it never interleaves with an emitter tick mutating the city
        if auth_on and x_api_key != layer_keys[call.requesting_layer]:
            events.emit("actuator_rejected", "actuator call rejected: bad or missing X-Api-Key", reason="unauthorized")
            raise HTTPException(401, f"missing or invalid X-Api-Key header for {call.requesting_layer}")
        try:
            return JSONResponse(actuation.execute(call))
        except CallRefused as exc:
            raise HTTPException(exc.status_code, exc.detail)

    # ---- the partners' own doors, after ours (POST /actuators/call must win over /actuators/{action}) ----
    app.include_router(brain_router(reading_log, city, brain_door))      # GET /readings, /topology, /capabilities, POST /actuators/{action}
    app.include_router(guardian_router(guardian_door))                   # POST /tools/{action}
    app.mount("/", mcp_asgi)                                             # /mcp; last, since a mount at / matches every path

    return app


app = create_app()
