"""REST API around the mock Guardian."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from mocks.guardian.engine import MockGuardian


class VerdictRequest(BaseModel):
    reading: dict[str, Any]


class ConfigRequest(BaseModel):
    default: str = "trusted"
    overrides: dict[str, str] = {}
    down: bool = False
    quarantined: list[str] = []


def build_app(guardian: MockGuardian) -> FastAPI:
    app = FastAPI(title="mock-guardian")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/verdicts")
    def verdicts(request: VerdictRequest) -> dict[str, Any]:
        if guardian.down:
            raise HTTPException(status_code=503, detail="guardian is down (scripted)")
        return guardian.verdict(request.reading)

    @app.get("/quarantine/{device_id}")
    def quarantine(device_id: str) -> dict[str, Any]:
        if guardian.down:
            raise HTTPException(status_code=503, detail="guardian is down (scripted)")
        return {"device_id": device_id, "quarantined": device_id in guardian.quarantined}

    @app.post("/admin/config")
    def configure(request: ConfigRequest) -> dict[str, Any]:
        return guardian.configure(request.default, request.overrides, request.down, request.quarantined)

    return app
