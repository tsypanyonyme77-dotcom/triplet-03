"""What a person or a partner does to a running Brain: answer an approval, log in, start Sleep, take back a verdict, run a scenario."""

from __future__ import annotations

import hmac
import json
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from brain import config
from brain.runtime import BrainService
from brain.security import Security

if TYPE_CHECKING:
    from brain.api import Hub


def _test_book_order(path: Path) -> tuple[str, int]:
    """d2 before d10: by the number in the file name, not by its spelling."""
    digits = "".join(c for c in path.stem if c.isdigit())
    return path.stem.rstrip("0123456789"), int(digits or 0)


def register(app: FastAPI, hub: Hub, service: Callable[[], BrainService], security: Security) -> None:
    @app.get("/api/approvals")
    def approvals() -> dict[str, Any]:
        """High-impact calls waiting for a person (`approval.mode: human`)."""
        running = service()
        if running.approvals is None:
            return {"mode": "off", "pending": []}
        return {"mode": "human", "pending": running.approvals.pending()}

    @app.post("/api/approvals/{pending_id}")
    async def answer_approval(pending_id: str, body: dict[str, str], request: Request) -> dict[str, Any]:
        """A person grants or denies one pending approval. A grant puts the held call back through the gate, which checks everything again."""
        running = service()
        if running.approvals is None:
            raise HTTPException(409, "approval.mode is off: high-impact calls are held, not queued for a person")
        if body.get("decision") not in ("grant", "deny"):
            raise HTTPException(422, "decision must be 'grant' or 'deny'")
        try:
            running.approvals.status(pending_id)
        except KeyError:
            raise HTTPException(404, f"no pending approval {pending_id}") from None
        caller = getattr(request.state, "caller", None)
        approver = caller.label if caller is not None else "operator"
        if body["decision"] == "deny":
            running.approvals.deny(pending_id, approver, body.get("reason", ""))
            return {"state": "denied"}
        granted = running.approvals.grant(pending_id, approver)
        actions = await running.reoffer(pending_id)
        return {"state": "granted", "approval_id": granted.approval_id, "expires_at": granted.expires_at.isoformat(), "actions": actions}

    @app.post("/api/login")
    async def login(body: dict[str, str]):
        presented = body.get("token", "")
        for label, token, _ in security.tokens():
            if presented and hmac.compare_digest(presented.encode(), token.encode()):
                response = JSONResponse({"as": label})
                response.set_cookie(security.config.cookie_name, presented, httponly=True, samesite="strict")
                return response
        raise HTTPException(401, {"error": "invalid_token"})

    @app.post("/api/logout")
    def logout() -> JSONResponse:
        response = JSONResponse({"status": "logged out"})
        response.delete_cookie(security.config.cookie_name)
        return response

    @app.get("/api/llm")
    def llm_status() -> dict[str, Any]:
        return hub.llm_report()

    @app.post("/api/llm/mode")
    def llm_mode(body: dict[str, str]) -> dict[str, Any]:
        """A person chooses the scripted team (`scripted`) or hands the choice back to the model's own health (`auto`)."""
        if body.get("mode") not in ("scripted", "auto"):
            raise HTTPException(422, "mode must be 'scripted' or 'auto'")
        hub.llm_health.force(body["mode"] == "scripted")
        return hub.llm_report()

    @app.post("/api/llm/check")
    async def llm_check() -> dict[str, Any]:
        return await hub.check_llm()

    @app.post("/api/sleep", status_code=202)
    async def start_sleep() -> dict[str, str]:
        hub.start_sleep()
        return {"status": "sleeping"}

    @app.get("/api/sleep/last")
    def last_sleep() -> dict[str, Any]:
        folder = hub.folder(hub.partners.brain.learned_dir)
        path = folder / "last-sleep.json" if folder else None
        if path is None or not path.is_file():
            raise HTTPException(404, "the Brain has not slept yet")
        return json.loads(path.read_text())

    @app.post("/api/retractions", status_code=202)
    def retract(body: dict[str, str], request: Request) -> dict[str, Any]:
        """For the Guardian: take back a verdict. Later actions that cite the reading stop; sleep forgets what it taught."""
        caller = getattr(request.state, "caller", None)
        if caller is not None and caller.label != "guardian":  # the Twin holds a push token too, and must not unsay the Guardian
            raise HTTPException(403, {"error": "retraction_is_the_guardians", "message": "only the Guardian's push token may retract a verdict"})
        reading_id, reason = body.get("reading_id", ""), body.get("reason", "")
        if not reading_id or not reason:
            raise HTTPException(422, "send {\"reading_id\": \"<sensor_id>#<sequence_no>\", \"reason\": \"why\"}")
        try:
            done = service().retract(reading_id, reason)
        except ValueError as error:  # a finished scenario run has closed its audit log
            raise HTTPException(409, "this run has finished and its audit log is closed; retract while the Brain is running") from error
        if done is None:
            raise HTTPException(404, f"the Brain has no reading {reading_id}")
        return done

    @app.get("/api/scenarios")
    def scenarios() -> dict[str, Any]:
        folder = config.home() / "scenarios"
        items = []
        for path in sorted(folder.glob("*.json"), key=_test_book_order):
            definition = json.loads(path.read_text())
            items.append({key: definition.get(key) for key in ("id", "name", "short", "layers", "claim", "description", "expected_brain")})
        return {"scenarios": items, "runnable": hub.mocks != "none", "running": hub.running, "last_result": hub.last_result}

    @app.post("/api/scenarios/{scenario_id}/run", status_code=202)
    async def run(scenario_id: str, speed: float = Query(1.0, ge=0, le=20)) -> dict[str, str]:
        return {"run_id": hub.start_scenario(scenario_id, speed)}
