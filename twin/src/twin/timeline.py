"""The live timeline (R3): the events of all three layers, merged by timestamp. The partners are read
over GET {url}/events, so a real layer shows up by exposing the same format (twin/INTERFACE.md); one
that cannot be reached is reported, it never stops the timeline."""
from __future__ import annotations

import asyncio
from typing import Any

import httpx

from twin.events import EventLog

PARTNER_TIMEOUT_S = 1.5
PARTNER_EVENTS = 1000
# periodic chatter: left out by default so that cause and effect stay readable, and flagged `routine`
# when asked for
NOISE = {"reading_emitted", "readings_verified"}


async def _partner(client: httpx.AsyncClient, layer: str, url: str) -> tuple[str, list[dict[str, Any]], str | None]:
    if not url:
        return layer, [], "not configured"
    try:
        resp = await client.get(f"{url}/events", params={"limit": PARTNER_EVENTS}, timeout=PARTNER_TIMEOUT_S)
        resp.raise_for_status()
        events = resp.json()["events"]
        return layer, [{**e, "layer": layer} for e in events if isinstance(e, dict) and "ts" in e], None
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        return layer, [], f"{type(exc).__name__}: {exc}"[:200]


def is_routine(event: dict[str, Any]) -> bool:
    return event["kind"] in NOISE


async def collect(own: EventLog, partners: dict[str, str], since: str = "", limit: int = 2000,
                  routine: bool = False) -> dict[str, Any]:
    """Every event at or after `since` (an ISO timestamp), oldest first, and each layer's state. With
    `routine`, the periodic chatter too, each event flagged `routine` true or false."""
    async with httpx.AsyncClient() as client:
        answers = await asyncio.gather(*(_partner(client, layer, url) for layer, url in partners.items()))
    merged = own.recent(limit)
    layers = {own.layer: {"reachable": True, "error": None}}
    for layer, events, error in answers:
        merged += events
        layers[layer] = {"reachable": error is None, "error": error}
    kept = sorted(({**e, "routine": is_routine(e)} if routine else e for e in merged
                   if e["ts"] >= since and (routine or not is_routine(e))), key=lambda e: e["ts"])
    return {"layers": layers, "events": kept[-limit:]}
