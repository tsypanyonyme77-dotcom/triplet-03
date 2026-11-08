"""WebSockets: /v1/ws/verdicts (verdicts + alerts for the Brain) and /v1/ws/timeline (all audit events, R3).
Auth with the X-API-Key header or ?api_key= (browsers cannot set WS headers)."""

from __future__ import annotations

import contextlib

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from guardian.adapters.brain_api.deps import caller_for

router = APIRouter(prefix="/v1/ws", tags=["websocket"])


async def _stream(ws: WebSocket, channel: str) -> None:
    g = ws.app.state.guardian
    key = ws.headers.get("x-api-key") or ws.query_params.get("api_key")
    if caller_for(g, key) is None:
        await ws.close(code=4401, reason="auth_required")
        return
    await ws.accept()
    q = g.emitter.subscribe(channel)
    try:
        while True:
            await ws.send_json(await q.get())
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        g.emitter.unsubscribe(channel, q)
        with contextlib.suppress(Exception):
            await ws.close()


@router.websocket("/verdicts")
async def ws_verdicts(ws: WebSocket) -> None:
    await _stream(ws, "verdicts")


@router.websocket("/timeline")
async def ws_timeline(ws: WebSocket) -> None:
    await _stream(ws, "timeline")
