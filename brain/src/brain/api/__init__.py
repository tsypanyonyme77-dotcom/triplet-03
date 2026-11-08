"""The Brain's HTTP surface: a live event stream for the timeline screen, and read-only
views of what the Brain knows and decided.

    GET  /events                      Server-Sent Events: every timeline event, replayed then live
    POST /api/events                  partner layers push their own events onto the same timeline
    GET  /api/scenarios               Test Book scenarios available to run
    POST /api/retractions             the Guardian takes back a verdict on a reading
    GET /api/llm, POST /api/llm/mode, /api/llm/check   is the hosted model answering; choose the scripted team; ask it now
    POST /api/sleep                   learn from the stored episodes now; GET /api/sleep/last is the last report
    POST /api/scenarios/{id}/run      one trigger per scenario (standalone mode)
    GET  /api/incidents               incidents of the current run
    GET  /api/incidents/{id}/graph    everything linked to one incident, as nodes and edges
    GET  /api/decisions/{id}          the provenance of one decision
    GET  /api/topology  /health  /schemas  /schemas/{name}
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException

from brain import config
from brain.adapters import open_twin
from brain.adapters.tls import guardian_client
from brain.api.routes import control, events, explain, pages, views
from brain.backends import open_backends
from brain.config import ModelsConfig, PartnersConfig, Policy
from brain.contracts import TimelineEvent
from brain.llm_health import LLMHealth, probe_into
from brain.observability import Metrics
from brain.persistence import live_session
from brain.runtime import BrainService
from brain.security import Security, install
from brain.telemetry import SpanSink
from brain.timeline import JsonlSink, Timeline, read_log

STATIC = Path(__file__).parent / "static"


class Broadcaster:
    """A timeline sink that keeps recent events and fans them out to connected screens."""

    def __init__(self, capacity: int = 5000, spans: Any = None) -> None:
        self.buffer: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self.metrics = Metrics()
        self.spans = spans  # a telemetry.SpanSink, or None

    def write(self, event: TimelineEvent) -> None:
        self.metrics.write(event)
        if self.spans is not None:
            try:
                self.spans.write(event)
            except Exception:  # telemetry never stops the Brain
                logging.getLogger("brain.telemetry").exception("a span could not be made; spans are switched off for this run")
                self.spans = None
        self.publish(event.model_dump(mode="json", exclude_none=True))

    def publish(self, record: dict[str, Any]) -> None:
        self.buffer.append(record)
        for queue in self._subscribers:
            queue.put_nowait(record)

    def reset(self, reason: str) -> None:
        """A new run starts: forget the old one and tell every screen to clear."""
        self.buffer.clear()
        self.write(TimelineEvent(type="brain.session.reset", data={"reason": reason}))

    async def stream(self, replay: bool = True, follow: bool = True) -> AsyncIterator[str]:
        queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._subscribers.add(queue)
        backlog = list(self.buffer) if replay else []  # no await since subscribing: nothing is missed or doubled
        try:
            for record in backlog:
                yield _sse(record)
            while follow:
                try:
                    yield _sse(await asyncio.wait_for(queue.get(), timeout=15))
                except TimeoutError:
                    yield ": keep-alive\n\n"
        finally:
            self._subscribers.discard(queue)


def _sse(record: dict[str, Any]) -> str:
    return f"id: {record.get('id', '')}\ndata: {json.dumps(record, ensure_ascii=False)}\n\n"


class Hub:
    """Owns the running Brain behind the API: one scenario at a time, or a live connection."""

    def __init__(self, partners: PartnersConfig, policy: Policy, models: ModelsConfig,
                 mocks: str = "inproc", log_dir: Path | None = None, fresh: bool = False) -> None:
        self.partners, self.policy, self.models = partners, policy, models
        self.mocks = mocks  # inproc | spawn | none (live partners)
        self.log_dir = log_dir
        self.fresh = fresh  # live mode: forget the saved state instead of continuing it
        endpoint = os.environ.get("OTLP_ENDPOINT") or partners.observability.otlp_endpoint  # the Compose obs profile sets it
        self.broadcaster = Broadcaster(spans=SpanSink.from_endpoint(endpoint, partners.observability.service_name) if endpoint else None)
        self._narrator: Any = None
        self.service: BrainService | None = None
        self.running: str | None = None
        self.last_result: dict[str, Any] | None = None
        self._task: asyncio.Task[None] | None = None
        self._sleeping: asyncio.Task[None] | None = None
        self.llm_health = LLMHealth(emit=self._say)  # outlives a scenario, so choosing the scripted team stays chosen
        self._watching: asyncio.Task[None] | None = None
        self.sleep_suite: list[str] | None = None  # the scenarios a sleep checks a lesson against (default: the whole Test Book)

    def _say(self, kind: str, subject: str | None, data: dict[str, Any]) -> None:
        self.broadcaster.write(TimelineEvent(type=kind, subject=subject, data=data))

    def llm_report(self) -> dict[str, Any]:
        return {"configured": self.models.team.llm, **self.llm_health.snapshot()}

    def _probe_target(self) -> tuple[str, str] | None:
        spec, key = self.models.roles.get("fast", ""), os.environ.get("GROQ_API_KEY", "")
        return (spec.removeprefix("groq:"), key) if spec.startswith("groq:") and key else None

    async def check_llm(self) -> dict[str, Any]:
        """Ask the hosted model now whether the key and the quota are good. Records the answer like a real call would."""
        target = self._probe_target()
        if target is None:
            return {"ok": None, "error": "no Groq key or no Groq model is configured; only real calls are watched", **self.llm_report()}
        return {**await probe_into(self.llm_health, *target), "configured": self.models.team.llm}

    def watch_llm(self) -> None:
        """Start (once) the loop that checks the hosted model while no deliberation is using it, so an outage shows before the next one."""
        interval = self.models.team.probe_s
        if not self.models.team.llm or interval <= 0 or self._watching is not None or self._probe_target() is None:
            return

        async def loop() -> None:
            while True:
                await asyncio.sleep(interval)
                if not self.llm_health.forced:
                    await self.check_llm()

        self._watching = asyncio.create_task(loop())

    def narrator(self) -> Any:
        """The model that rephrases a one-line explanation, built once; None if it cannot be built (the code's own sentence is used)."""
        if self._narrator is None:
            try:
                from langchain.chat_models import init_chat_model

                role = self.models.explain.role
                model = init_chat_model(self.models.roles[role], **self.models.options_for(role))
                self._narrator = lambda prompt: str(model.invoke(prompt).content)
            except Exception:  # noqa: BLE001 - the narrator is optional; without it the screen shows plain text
                self._narrator = False
        return self._narrator or None

    def folder(self, configured: str | None) -> Path | None:
        if not configured:
            return None
        path = Path(configured)
        return path if path.is_absolute() else config.home() / path

    def start_sleep(self) -> None:
        """Quiet-time learning, started from the screen: the sleep events go onto the same stream the screen reads."""
        from brain.mind.sleep import sleep

        episodes, learned = self.folder(self.partners.brain.episodes_dir), self.folder(self.partners.brain.learned_dir)
        if episodes is None or learned is None:
            raise HTTPException(409, "set brain.episodes_dir and brain.learned_dir in partners.yaml to let the Brain sleep")
        if self.running is not None or (self._sleeping is not None and not self._sleeping.done()):
            raise HTTPException(409, "the Brain is busy: a scenario or a sleep is still running")
        self._sleeping = asyncio.create_task(
            sleep(episodes, learned, self.policy, Timeline([self.broadcaster]), suite=self.sleep_suite, models=self.models)
        )

    async def wait_sleep(self) -> None:
        if self._sleeping is not None:
            await self._sleeping

    def start_scenario(self, scenario_id: str, speed: float) -> str:
        from brain import scenario as runner

        if self.mocks == "none":
            raise HTTPException(409, "this Brain is connected to live partners; scenarios are triggered on the Twin")
        if self.running is not None:
            raise HTTPException(409, f"scenario {self.running} is still running")
        try:
            definition = runner.load_scenario(scenario_id)
        except FileNotFoundError as error:
            raise HTTPException(404, str(error)) from error

        run_id = f"{scenario_id}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
        self.running, self.last_result = scenario_id, None
        self.broadcaster.reset(f"scenario {scenario_id}")
        if self.models.team.llm:
            self.llm_health.announce(again=True)  # the reset cleared the screen's idea of the model
            self.watch_llm()

        async def play() -> None:
            context = runner.inproc_partners() if self.mocks == "inproc" else runner.spawned_partners(self.partners)
            try:
                async with open_backends(self.partners.graph, self.models, run_id) as backends:
                    if backends.note:
                        logging.getLogger("brain.api").warning("%s", backends.note)  # a store is away: the log and brain_store_up say so
                    result = await runner.run_scenario(
                        definition, context, partners=self.partners, policy=self.policy, models=self.models,
                        store=backends.store, kb=backends.kb, speed=speed, log_dir=self.log_dir,
                        extra_sinks=[self.broadcaster], on_service=self._attach, llm_health=self.llm_health,
                    )
                self.last_result = {
                    "scenario": scenario_id, "passed": result.passed, "log": str(result.log_path) if result.log_path else None,
                    "checks": [{"name": c.name, "passed": c.passed, "detail": c.detail} for c in result.checks],
                }
            except Exception as error:  # noqa: BLE001 - a failed scenario is reported on the screen, not a server error
                self.last_result = {"scenario": scenario_id, "passed": False, "error": f"{type(error).__name__}: {error}"}
                self.broadcaster.write(TimelineEvent(type="brain.scenario.failed", subject=scenario_id, data=self.last_result))
            finally:
                self.running = None

        self._task = asyncio.create_task(play())
        return run_id

    def _attach(self, service: BrainService) -> None:
        self.service = service

    async def run_live(self) -> None:
        """Connect to the configured partners and stay connected (the `--live` mode)."""
        from brain.adapters import open_guardian, with_gateway

        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        sinks: list[Any] = [self.broadcaster]
        state = None
        if self.log_dir is not None:
            brain = self.partners.brain
            state, log_path, resumed = live_session(brain.state_file, brain.state_max_age_s, config.home(), self.log_dir, self.fresh)
            if resumed:
                # The screen gets back everything that happened before the restart.
                self.broadcaster.buffer.extend(read_log(log_path))
            sinks.append(JsonlSink(log_path, resume=resumed))
        self.watch_llm()
        async with open_backends(self.partners.graph, self.models, f"live-{stamp}") as backends:
            if backends.note:
                logging.getLogger("brain.api").warning("%s", backends.note)
            async with guardian_client(self.partners.guardian.url, self.partners.guardian.tls) as client:
                async with open_twin(self.partners.twin) as twin:
                    guardian = open_guardian(self.partners.guardian, client)
                    service = BrainService(self.partners, self.policy, with_gateway(twin, guardian, self.partners.guardian), guardian,
                                           Timeline(sinks), self.models, store=backends.store, kb=backends.kb, state=state,
                                           llm_health=self.llm_health)
                    await service.start()
                    self._attach(service)
                    await service.run()

    async def wait(self) -> None:
        if self._task is not None:
            await self._task


def create_app(hub: Hub) -> FastAPI:
    mcp_app, tool_registry = None, None
    if hub.partners.mcp.enabled:
        from brain.mcpserver import build_mcp, transport_security

        mcp_server, tool_registry = build_mcp(hub)
        mcp_app = mcp_server.streamable_http_app(streamable_http_path="/mcp", transport_security=transport_security(hub.partners.mcp.allowed_hosts))

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if mcp_app is None:
            yield
        else:  # a mounted app's own lifespan does not run by itself: the MCP session manager needs it
            async with mcp_app.router.lifespan_context(mcp_app):
                yield

    app = FastAPI(title="City Brain", version="0.2.0", lifespan=lifespan)
    security = Security(hub.partners.security)
    install(app, security)

    def service() -> BrainService:
        if hub.service is None:
            raise HTTPException(404, "no run yet: start a scenario or connect the Brain to its partners")
        return hub.service

    pages.register(app, hub, service, tool_registry)
    events.register(app, hub, service)
    control.register(app, hub, service, security)
    views.register(app, hub, service)
    explain.register(app, hub, service)

    if mcp_app is not None:
        app.mount("/", mcp_app)  # last: every other route is matched first
    return app
