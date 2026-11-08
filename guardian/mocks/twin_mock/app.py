"""Twin mock HTTP app (port 8101): /health, /readings (pull), /tools/{name}, /inject/{kind}, /tool-log.
In push mode a background loop POSTs batches to the Guardian's /v1/readings."""

from __future__ import annotations

import asyncio
import contextlib
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import Body, FastAPI, HTTPException

from guardian.clock import Clock, SystemClock
from mocks.twin_mock.sim import INJECTIONS, Simulator


async def push_loop(sim: Simulator, client: httpx.AsyncClient, api_key: str, clock: Clock,
                    tick_s: float = 1.0) -> None:
    while True:
        batch = sim.step()
        if batch:
            with contextlib.suppress(httpx.HTTPError):
                await client.post("/v1/readings", json=batch, headers={"X-API-Key": api_key})
        await clock.sleep(tick_s)


def create_twin_app(sim: Simulator | None = None, *, push: bool | None = None) -> FastAPI:
    clock: Clock = sim.clock if sim else SystemClock()
    sim = sim or Simulator(clock, os.environ.get("TWIN_HMAC_KEY", "dev-twin-key"),
                           speed=float(os.environ.get("TWIN_SPEED", "1")))
    push = (os.environ.get("TWIN_MODE", "push") == "push") if push is None else push

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        task = None
        if push:
            client = httpx.AsyncClient(base_url=os.environ.get("GUARDIAN_URL", "http://localhost:8100"), timeout=5)
            task = asyncio.create_task(push_loop(sim, client, os.environ.get("TWIN_API_KEY", ""), clock))
        yield
        if task:
            task.cancel()

    app = FastAPI(title="Twin mock", lifespan=lifespan)
    app.state.sim = sim

    @app.get("/health")
    async def health() -> dict[str, Any]:
        if sim.silence_all:
            raise HTTPException(503, "twin silenced")
        return {"status": "ok", "sensors": len(sim.sensors)}

    @app.get("/readings")
    async def readings(cursor: int = 0) -> dict[str, Any]:
        if not push:
            sim.step()  # pull mode: time advances when the Guardian polls
        nxt, items = sim.since(cursor)
        return {"cursor": nxt, "readings": items}

    @app.post("/tools/{name}")
    async def tool(name: str, call: dict[str, Any] = Body(...)) -> dict[str, Any]:
        if sim.silence_all:
            raise HTTPException(503, "twin silenced")
        return sim.tool(name, call)

    @app.post("/inject/{kind}")
    async def inject(kind: str, params: dict[str, Any] | None = Body(default=None)) -> dict[str, Any]:
        if kind not in INJECTIONS:
            raise HTTPException(404, f"unknown injection {kind}; one of {INJECTIONS}")
        return sim.inject(kind, params or {})

    @app.get("/tool-log")
    async def tool_log() -> list[dict[str, Any]]:
        return sim.tool_log

    @app.get("/state")
    async def state() -> dict[str, Any]:
        return {"rain": sim.rain, "flow": sim.flow, "level": sim.level, "valve_closed": sim.valve_closed,
                "grid_connected": sim.grid_connected, "isolated": sorted(sim.isolated),
                "quarantined": sorted(sim.quarantined), "overrides": sorted(sim.overrides)}

    return app
