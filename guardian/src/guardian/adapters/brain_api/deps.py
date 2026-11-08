"""Shared API helpers: API-key auth (X-API-Key → caller identity), the error model, X-Scenario-Id."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import Header, HTTPException, Request
from fastapi.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from guardian.adapters.schemas import ErrorOut
from guardian.audit.logger import scenario_id_var

if TYPE_CHECKING:
    from guardian.main import Guardian


def error(status: int, code: str, message: str, field: str | None = None,
          headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(ErrorOut(error=code, message=message, field=field).model_dump(), status, headers=headers)


def fail(status: int, code: str, message: str, field: str | None = None) -> HTTPException:
    return HTTPException(status, {"error": code, "message": message, "field": field})


def guardian_of(request: Request) -> Guardian:
    return request.app.state.guardian


def caller_for(g: Guardian, key: str | None) -> str | None:
    return g.settings.api_keys().get(key or "")


async def require_caller(request: Request, x_api_key: str | None = Header(default=None)) -> str:
    who = caller_for(guardian_of(request), x_api_key)
    if who is None:
        raise fail(401, "auth_required", "missing or invalid X-API-Key")
    return who


class ScenarioMiddleware:
    """Carries X-Scenario-Id into every audit event emitted while serving the request."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        sid: Any = None
        if scope["type"] in ("http", "websocket"):
            for k, v in scope.get("headers", []):
                if k == b"x-scenario-id":
                    sid = v.decode(errors="replace")[:64]
        token = scenario_id_var.set(sid)
        try:
            await self.app(scope, receive, send)
        finally:
            scenario_id_var.reset(token)
