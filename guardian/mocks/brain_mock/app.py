"""Brain mock HTTP app (port 8102). Subscribes to /v1/ws/verdicts (logs what it would do) and exposes
triggers used by scenarios: /brain/check-flood, /brain/call (raw call, good or bad), /brain/decisions."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import Body, FastAPI

from mocks.brain_mock.brain import BrainMock


async def ws_listener(brain: BrainMock, url: str, api_key: str) -> None:
    import websockets

    while True:
        try:
            async with websockets.connect(url, additional_headers={"X-API-Key": api_key}) as ws:
                async for raw in ws:
                    msg = json.loads(raw)
                    if msg.get("type") == "alert":
                        brain.note("alert_received", alert=msg["alert"])
                    elif msg.get("type") == "verdict" and msg["verdict"]["status"] != "trusted":
                        v = msg["verdict"]
                        brain.note("would_ignore", sensor_id=v["reading_ref"]["sensor_id"], status=v["status"],
                                   reasons=v["reasons"])
        except Exception:
            await asyncio.sleep(2)


def create_brain_app() -> FastAPI:
    base = os.environ.get("GUARDIAN_URL", "http://localhost:8100")
    key = os.environ.get("BRAIN_API_KEY", "")
    brain = BrainMock(httpx.AsyncClient(base_url=base, timeout=5), key)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        task = asyncio.create_task(ws_listener(brain, base.replace("http", "ws", 1) + "/v1/ws/verdicts", key))
        yield
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    app = FastAPI(title="Brain mock", lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/brain/check-flood")
    async def check_flood(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        return await brain.check_flood(body.get("sensor_id", "wl-port-03"), body.get("zone_id", "zone-07"))

    @app.post("/brain/call")
    async def call(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        return await brain.send_call(body["actuator_id"], body["action"], body.get("params", {}),
                                     zone_id=body.get("zone_id"), trust_ref=body.get("trust_ref"),
                                     justification=body.get("justification", "brain mock"),
                                     incident_id=body.get("incident_id"))

    @app.post("/brain/verdict")
    async def verdict(body: dict[str, Any] = Body(...)) -> dict[str, Any]:
        return await brain.request_verdict(body["sensor_id"], body.get("sequence_no"))

    @app.get("/brain/decisions")
    async def decisions() -> list[dict[str, Any]]:
        return brain.decisions[-200:]

    return app
