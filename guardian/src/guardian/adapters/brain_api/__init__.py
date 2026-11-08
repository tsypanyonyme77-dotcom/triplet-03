"""Brain-facing API (FastAPI routers, error model, auth, scenario header). `install` mounts everything."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from guardian.adapters.brain_api import actuator_calls, system, timeline_ui, verdicts, ws
from guardian.adapters.brain_api.deps import ScenarioMiddleware, error

if TYPE_CHECKING:
    from guardian.main import Guardian


def install(app: FastAPI, guardian: Guardian) -> None:
    app.add_middleware(ScenarioMiddleware)

    @app.exception_handler(RequestValidationError)
    async def _validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        err: dict[str, Any] = exc.errors()[0] if exc.errors() else {}
        loc = [str(p) for p in err.get("loc", []) if p not in ("body", "query", "path", "header")]
        return error(422, "schema_invalid", str(err.get("msg", "invalid request"))[:300], ".".join(loc) or None)

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        d = exc.detail if isinstance(exc.detail, dict) else {"error": "http_error", "message": str(exc.detail)}
        return error(exc.status_code, d.get("error", "http_error"), d.get("message", ""), d.get("field"),
                     headers=getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def _crash(_: Request, exc: Exception) -> JSONResponse:
        guardian.audit.emit("error", f"unhandled API error: {type(exc).__name__}", data={"kind": "api_error"})
        return error(500, "internal_error", "internal error; treat any data as unknown")

    for module in (system, verdicts, actuator_calls, ws, timeline_ui):
        app.include_router(module.router)
