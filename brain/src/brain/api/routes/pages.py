"""The page, its scripts, and the discovery routes: the agent card, the keys, the metrics and the health check."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from brain.contracts import CONTRACT_VERSION
from brain.runtime import BrainService

if TYPE_CHECKING:
    from brain.api import Hub

STATIC = Path(__file__).resolve().parent.parent / "static"


def register(app: FastAPI, hub: Hub, service: Callable[[], BrainService], tool_registry: Any) -> None:
    if (STATIC / "index.html").exists():

        @app.get("/", include_in_schema=False)
        def dashboard() -> FileResponse:
            return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/canopy3d.js", include_in_schema=False)
    def canopy_module() -> FileResponse:
        return FileResponse(STATIC / "canopy3d.js", media_type="text/javascript", headers={"Cache-Control": "no-store"})

    @app.get("/story.js", include_in_schema=False)
    def story_js() -> FileResponse:
        return FileResponse(STATIC / "story.js", media_type="text/javascript", headers={"Cache-Control": "no-store"})

    @app.get("/brainshell.js", include_in_schema=False)
    def brain_shell_module() -> FileResponse:
        return FileResponse(STATIC / "brainshell.js", media_type="text/javascript", headers={"Cache-Control": "no-store"})

    # The 3D canopy's library (three.js, MIT) is a pinned copy kept in the repo: the screen must work with no network.
    if (STATIC / "vendor").is_dir():
        app.mount("/vendor", StaticFiles(directory=STATIC / "vendor"), name="vendor")

    @app.get("/.well-known/agent-card.json")
    def agent_card() -> dict[str, Any]:
        """Discovery for other agents: what this Brain offers, how to call it, how to authenticate."""
        tools = [t for t in (tool_registry.list() if tool_registry else []) if t.source == "server"]
        return {
            "name": "City Brain", "version": app.version, "contract_version": CONTRACT_VERSION,
            "description": "The decision layer of a smart-city triplet. Brain-inspired: it models functions of a brain as engineering and is never described as conscious. These skills only read; only its gate can act.",
            "skills": [{"id": t.name, "description": t.doc, "scope": t.scope, "input_schema": t.input_schema} for t in tools],
            "endpoints": {"mcp": "/mcp" if tool_registry else None, "events": "/events", "schemas": "/schemas", "openapi": "/openapi.json", "interface_card": "INTERFACE.md"},
            "authentication": {"schemes": ["bearer"], "scopes": ["read", "analyse", "push", "approve", "admin"], "note": "required off loopback"},
            "status": "agreed",
        }

    @app.get("/.well-known/jwks.json")
    def jwks() -> dict[str, Any]:
        """The Brain's public signing keys (EdDSA), so a partner can verify its calls without a shared secret."""
        from brain.contracts.keyring import KeyRing

        return KeyRing.from_config(hub.partners.security.keys).jwks("brain")

    @app.get("/metrics", response_class=PlainTextResponse)
    def metrics() -> PlainTextResponse:
        """Prometheus text format, computed from the timeline (needs the read scope off loopback)."""
        return PlainTextResponse(hub.broadcaster.metrics.render(), media_type="text/plain; version=0.0.4; charset=utf-8")

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok", "mode": "live" if hub.mocks == "none" else f"standalone ({hub.mocks} mocks)",
            "running": hub.running, "default_view": hub.partners.brain.default_view, "graph_backend": hub.partners.graph.backend,
            "team": "llm" if hub.models.team.llm else ("scripted" if hub.models.team.enabled else "off"),
            "departments": hub.models.team.departments,  # on: Fire, Ambulance and medical, Traffic control, Disaster response and Utilities have agent desks (Police has its own team)
            "events_buffered": len(hub.broadcaster.buffer),
        }
