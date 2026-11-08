"""The live event stream and the route partners push their own events through."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from brain.contracts import TimelineEvent
from brain.runtime import BrainService

if TYPE_CHECKING:
    from brain.api import Hub


# The Twin's run checks look for these kinds (twin/src/twin/timeline.py); every other event keeps its own name.
TWIN_KINDS = {"brain.incident.opened": "incident_reported", "brain.action.requested": "actuator_called"}


def twin_event(record: dict[str, Any]) -> dict[str, Any]:
    """One Brain CloudEvent in the Twin's timeline format: {ts, kind, message}."""
    kind = str(record.get("type", ""))
    data = record.get("data") if isinstance(record.get("data"), dict) else {}
    said = data.get("reason") or data.get("action") or data.get("type") or ""
    ts = str(record.get("time") or "")
    if len(ts) > 24 and ts.endswith("Z"):
        ts = ts[:23] + "Z"  # milliseconds, as the Twin writes them: it compares and sorts ts as strings
    return {"ts": ts, "kind": TWIN_KINDS.get(kind, kind.removeprefix("brain.")),
            "message": " ".join(str(x) for x in (record.get("subject") or "", said) if x)[:200]}


def register(app: FastAPI, hub: Hub, service: Callable[[], BrainService]) -> None:
    @app.get("/events", response_model=None)
    def events(replay: bool = True, once: bool = Query(False, description="send the backlog and close"),
               limit: int | None = Query(None, ge=1, le=5000, description="JSON {events:[{ts, kind, message}]} instead of the stream (the Twin's timeline format)")) -> StreamingResponse | dict[str, Any]:
        if limit is not None:
            return {"events": [twin_event(r) for r in list(hub.broadcaster.buffer)[-limit:] if str(r.get("type", "")).startswith("brain.")]}
        return StreamingResponse(
            hub.broadcaster.stream(replay=replay, follow=not once), media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/events", status_code=202)
    async def push_event(event: TimelineEvent, request: Request) -> dict[str, str]:
        """For the Twin and Guardian layers: put your own CloudEvents on the shared timeline.

        A partner speaks only inside its own namespace (`twin.`, `guardian.`): the `brain.` events are the Brain's, so a pushed
        one is refused. With tokens on, the source is the token's partner and the body's `source` cannot say otherwise."""
        caller = getattr(request.state, "caller", None)
        source = caller.label if caller is not None and caller.label not in ("push", "admin") else event.source

        def refuse(status: int, detail: Any, why: str) -> HTTPException:
            """A refusal is an event in the Brain's own log, so a person reading it sees the attempt and its reason. Nothing from the push goes in but its type and source."""
            if hub.service is not None:
                hub.service.timeline.emit("brain.push.refused", None, {"reason": why, "attempted_type": event.type[:80], "claimed_source": event.source[:40]})
            return HTTPException(status, detail)

        if event.source == "city-brain" or source == "city-brain":
            raise refuse(422, "source 'city-brain' is reserved; use your own layer's name, e.g. 'twin' or 'guardian'", "source_reserved")
        if event.type.startswith("brain."):
            raise refuse(403, {"error": "reserved_namespace", "message": "events named brain.* belong to the Brain"}, "reserved_namespace")
        if not event.type.startswith(f"{source}."):
            raise refuse(403, {"error": "type_not_allowed", "allowed": [f"{source}.*"]}, "type_not_allowed")
        record = event.model_dump(mode="json", exclude_none=True)
        hub.broadcaster.publish({**record, "source": source, "pushed": True})  # `pushed` lets any screen tell it from the Brain's own
        if event.type == "twin.live_reset" and hub.service is not None:
            await hub.service.twin_reset(str(event.subject or event.id))
        return {"accepted": event.id}
