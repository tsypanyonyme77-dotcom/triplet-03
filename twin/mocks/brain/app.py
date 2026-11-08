"""MOCK City Brain layer (stand-in, no real analysis), with an operator console.

- Receives the Twin's "new data available" notification (no payload).
- Polls the Guardian's verified readings every second and keeps an incident board
  (incident_rule.IncidentBoard).
- Operator actions (dispatch ambulance / police / fire truck, close / open the road) go through
  POST /api/incidents/{id}/actions, which builds the actuator call exactly as the City Brain
  would and sends it to the Twin. Manual by default: nothing is dispatched until an operator
  acts. BRAIN_AUTO_DISPATCH=1 or POST /api/mode turns on the auto rule (scenario runs, tests).
"""
from __future__ import annotations

import asyncio
import json
import os
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from contextlib import asynccontextmanager, suppress
from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

CONTRACT_VERSION = "2026-09-17"
TWIN_URL = os.environ.get("TWIN_URL", "http://localhost:8001").rstrip("/")
GUARDIAN_URL = os.environ.get("GUARDIAN_URL", "http://localhost:8003").rstrip("/")
TWIN_API_KEY = os.environ.get("TWIN_BRAIN_API_KEY", os.environ.get("TWIN_API_KEY", ""))
UI_DIR = Path(os.environ.get("MOCK_UI_DIR", Path(__file__).parent / "ui"))
LOG_DIR = os.environ.get("LOG_DIR", "")
AUTO_DISPATCH = os.environ.get("BRAIN_AUTO_DISPATCH", "").strip().lower() in ("1", "true", "yes", "on")
POLL_S = float(os.environ.get("BRAIN_POLL_S", "1"))

try:
    import incident_rule as rules  # next to this file (uvicorn --app-dir mocks/brain, or the Docker image)
except ModuleNotFoundError:  # loaded by path (tests)
    import importlib.util as _ilu
    import sys as _sys
    _spec = _ilu.spec_from_file_location("incident_rule", Path(__file__).parent / "incident_rule.py")
    rules = _ilu.module_from_spec(_spec)
    _sys.modules["incident_rule"] = rules
    _spec.loader.exec_module(rules)

class IncidentDesk:
    """The Brain's incident state for the current Twin run (reset when the Twin starts a new run)."""

    def __init__(self) -> None:
        self.auto = AUTO_DISPATCH
        self.readings: deque[dict[str, Any]] = deque(maxlen=200)  # what the Guardian vouched for, newest last
        self.reset(None)

    def reset(self, run_id: int | None) -> None:
        self.run_id = run_id
        self.board = rules.IncidentBoard()
        self.rule = rules.IncidentDispatchRule() if self.auto else None
        self.calls: deque[dict[str, Any]] = deque(maxlen=300)
        self.sim_time = 0.0

    async def poll_once(self, client: httpx.AsyncClient) -> None:
        try:
            status = (await client.get(f"{TWIN_URL}/live/status")).json()
            if status.get("run_id") != self.run_id:
                self.reset(status.get("run_id"))
                _emit("run_started", f"Twin run {self.run_id} ({status.get('scenario')}): incident board cleared",
                      run_id=self.run_id)
            self.sim_time = status.get("sim_time_s", self.sim_time)
        except (httpx.HTTPError, ValueError):
            pass  # not in live mode, or the Twin is down: keep what we have
        got = (await client.get(f"{GUARDIAN_URL}/verified/readings",
                                params={"after": _cursor["after"]})).json()
        _cursor["after"] = got["next"]
        for item in got["items"]:
            reading, verdict = item["reading"], item["verdict"]
            self.readings.append(item)
            if self.run_id is not None and reading["value"].get("run_id") not in (None, self.run_id):
                continue  # a report from an earlier run of the Twin
            now = reading["value"].get("sim_time_s", self.sim_time)
            new = self.board.observe(reading, verdict, now)
            if new:
                _emit("incident_reported", f"{new['incident_id']}: first trusted report ({new['first_type']}, "
                      f"{verdict['verdict_id']}){'' if self.rule else ', waiting for an operator'}",
                      incident_id=new["incident_id"], trust_ref=verdict["verdict_id"])
                if self.rule:
                    self.rule.notice(new, now)
        try:
            self.board.update_from_twin((await client.get(f"{TWIN_URL}/responses")).json()["responses"])
        except (httpx.HTTPError, ValueError, KeyError):
            pass
        if self.rule:
            for action, call in self.rule.due(self.board, self.sim_time):
                await self.send(client, action, call)

    async def send(self, client: httpx.AsyncClient, action: str, call: dict[str, Any]) -> dict[str, Any]:
        headers = {"X-Api-Key": TWIN_API_KEY} if TWIN_API_KEY else {}
        entry = {"at": _now(), "sim_time_s": self.sim_time, "action": action, "call": call}
        try:
            resp = await client.post(f"{TWIN_URL}/actuators/call", json=call, headers=headers)
            body = resp.json()
            result = body.get("result") or {"status": "error", "reason": str(body.get("detail", body))[:200]}
            entry.update(http=resp.status_code, result=result, replayed=body.get("replayed", False))
        except httpx.HTTPError as exc:
            result = {"status": "error", "reason": f"Twin unreachable: {exc}"}
            entry.update(http=None, result=result)
        self.calls.appendleft(entry)
        self.board.record_action(call["params"]["incident_id"], action, call, entry["http"] or 0, result)
        _emit("actuator_called", f"{action} on {call['params']['incident_id']}: {result.get('status')} "
              f"{result.get('unit_id', result.get('reason', '')) or ''}", action=action, result=result,
              idempotency_key=call.get("idempotency_key"))
        return entry


_cursor = {"after": 0}
desk = IncidentDesk()


async def _poll_forever() -> None:
    async with httpx.AsyncClient(timeout=2.0) as client:
        while True:
            try:
                await desk.poll_once(client)
            except Exception as exc:  # keep polling whatever happens once
                _emit("poll_failed", f"incident poll failed: {exc}")
            await asyncio.sleep(POLL_S)


@asynccontextmanager
async def _lifespan(app: FastAPI):
    task = asyncio.create_task(_poll_forever())
    yield
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task


app = FastAPI(title="Mock City Brain", lifespan=_lifespan)
_events: deque[dict[str, Any]] = deque(maxlen=1000)
_notify = {"count": 0, "last": None, "last_flush": 0.0}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _emit(kind: str, message: str, **data: Any) -> None:
    event = {"ts": _now(), "layer": "city_brain", "kind": kind, "message": message, "data": data}
    _events.append(event)
    if LOG_DIR:
        Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
        with (Path(LOG_DIR) / "city_brain.ndjson").open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(event) + "\n")


@app.get("/health")
def health():
    return {"status": "ok", "mock": True}


@app.post("/notify")
async def notify(request: Request):
    body = await request.json()
    _notify["count"] += 1
    _notify["last"] = _now()
    loop_time = asyncio.get_event_loop().time()
    if loop_time - _notify["last_flush"] >= 3.0:  # keep the timeline readable
        _emit("notified", "Twin says new readings are available (no payload)", twin_event=body.get("event"), total=_notify["count"])
        _notify["last_flush"] = loop_time
    return {"ok": True}


@app.get("/api/status")
def status():
    return {"notifications": _notify["count"], "last_notification": _notify["last"], "twin_url": TWIN_URL, "guardian_url": GUARDIAN_URL}


@app.get("/api/identity")
def identity():
    return {"layer": "city_brain", "twin_url": TWIN_URL, "guardian_url": GUARDIAN_URL}


@app.get("/api/readings")
def recent_readings(limit: int = 50):
    """What the Brain has read from the Guardian, newest first, each reading with the verdict vouching for it."""
    return {"items": list(desk.readings)[-limit:][::-1]}


class ModeRequest(BaseModel):
    auto: bool


@app.post("/api/mode")
def set_mode(req: ModeRequest):
    """Who decides from now on: the auto rule, or an operator at the console."""
    desk.auto = req.auto
    desk.rule = rules.IncidentDispatchRule() if req.auto else None
    _emit("mode_changed", f"decisions now come from {'the auto rule' if req.auto else 'an operator'}", auto=req.auto)
    return mode()


@app.get("/api/mode")
def mode():
    return {"auto_dispatch": desk.auto, "run_id": desk.run_id, "sim_time_s": desk.sim_time,
            "twin_url": TWIN_URL, "guardian_url": GUARDIAN_URL}


@app.get("/api/incidents")
def incidents():
    """The incident board: every incident with a trusted report, oldest first, with its status."""
    return {"contract_version": CONTRACT_VERSION, "run_id": desk.run_id, "sim_time_s": desk.sim_time,
            "auto_dispatch": desk.auto, "actions": sorted(rules.ACTIONS), "incidents": desk.board.list()}


class ActionRequest(BaseModel):
    action: str
    justification: str | None = None


@app.post("/api/incidents/{incident_id}/actions")
async def incident_action(incident_id: str, req: ActionRequest):
    """An operator action, sent to the Twin as the City Brain's actuator call."""
    incident = desk.board.incidents.get(incident_id)
    if incident is None:
        raise HTTPException(404, f"no trusted report of {incident_id} yet")
    if req.action not in rules.ACTIONS:
        raise HTTPException(422, f"unknown action {req.action!r}; one of {sorted(rules.ACTIONS)}")
    call = rules.build_call(incident, req.action, req.justification)
    async with httpx.AsyncClient(timeout=5.0) as client:
        return await desk.send(client, req.action, call)


@app.get("/api/actuator-calls")
def actuator_calls(limit: int = 100):
    """Every actuator call the Brain sent, newest first, with the Twin's answer."""
    return {"calls": list(desk.calls)[:limit]}


@app.get("/api/actuators")
async def actuator_catalog():
    """The Twin's actuator catalog (GET /actuators), as the Brain sees it."""
    async with httpx.AsyncClient(timeout=3.0) as client:
        try:
            return (await client.get(f"{TWIN_URL}/actuators")).json()
        except httpx.HTTPError as exc:
            raise HTTPException(502, f"cannot read the Twin's actuator catalog: {exc}")


@app.get("/api/units")
async def unit_status():
    """The Twin's emergency units (GET /units)."""
    async with httpx.AsyncClient(timeout=3.0) as client:
        try:
            return (await client.get(f"{TWIN_URL}/units")).json()
        except httpx.HTTPError as exc:
            raise HTTPException(502, f"cannot read the Twin's units: {exc}")


@app.get("/events")
def events(limit: int = 200):
    return {"events": list(_events)[-limit:]}


if UI_DIR.is_dir():  # last: the API routes above win over the console's files
    app.mount("/", StaticFiles(directory=UI_DIR, html=True), name="console")
