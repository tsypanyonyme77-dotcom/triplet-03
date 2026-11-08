""""Why was that done?": explanations of a decision, a held action or an incident, built from the run's own events."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import PlainTextResponse

from brain.explain import Explanation, explain_decision, explain_held, explain_incident
from brain.explain.render import narrate, to_markdown, to_sentence
from brain.runtime import BrainService

if TYPE_CHECKING:
    from brain.api import Hub


def register(app: FastAPI, hub: Hub, service: Callable[[], BrainService]) -> None:
    async def explanation(build: Any, key: str, format: str) -> Any:
        """Explain from the events of the current run. The same log always gives the same text; nothing here asks a model unless
        `explain.narrate` is `llm`, and then only for the one-line version."""
        kb = service().kb
        events = list(hub.broadcaster.buffer)
        try:
            built: Explanation = build(events, key, policy=hub.policy, kb=kb)
        except KeyError:
            raise HTTPException(404, f"nothing in this run to explain for {key}") from None
        if format == "md":
            return PlainTextResponse(to_markdown(built), media_type="text/markdown; charset=utf-8")
        narration = None
        if hub.models.explain.narrate == "llm":
            text, mode = await asyncio.to_thread(narrate, built, hub.narrator())
            narration = {"text": text, "mode": mode}
        return {**built.model_dump(mode="json"), "sentence": to_sentence(built), "narration": narration}

    @app.get("/api/decisions/{decision_id}/explanation")
    async def decision_explanation(decision_id: str, format: str = Query("json", pattern="^(json|md)$")) -> Any:
        return await explanation(explain_decision, decision_id, format)

    @app.get("/api/decisions/{decision_id}/prov")
    async def decision_prov(decision_id: str) -> Any:
        """The decision's explanation as W3C PROV-JSON."""
        from brain.explain.prov import to_prov

        events = list(hub.broadcaster.buffer)
        try:
            return to_prov(explain_decision(events, decision_id, policy=hub.policy, kb=service().kb))
        except KeyError:
            raise HTTPException(404, f"nothing in this run to explain for {decision_id}") from None

    @app.get("/api/held/{event_id}/explanation")
    async def held_explanation(event_id: str, format: str = Query("json", pattern="^(json|md)$")) -> Any:
        return await explanation(explain_held, event_id, format)

    @app.get("/api/incidents/{incident_id}/explanation")
    async def incident_explanation(incident_id: str, format: str = Query("json", pattern="^(json|md)$")) -> Any:
        return await explanation(explain_incident, incident_id, format)
