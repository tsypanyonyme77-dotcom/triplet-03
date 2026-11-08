"""The Twin's events on the City Brain's timeline screen (R3): POST {BRAIN_URL}/api/events, CloudEvents 1.0 with
type `twin.<kind>` and source `twin`, Bearer TWIN_PUSH_TOKEN when the Brain asks for tokens.

Only what another layer may see: never the engine's ground truth (`sim_*`) nor the periodic chatter. Pushed
once per emit tick, a bounded number at a time. A Brain that cannot be reached costs the timeline those
events, never the feed; that is reported once per outage, and what waits past the buffer is dropped.
"""
from __future__ import annotations

import uuid
from collections import deque
from typing import Any

import httpx

from twin.events import GROUND_TRUTH_PREFIX, EventLog
from twin.timeline import NOISE

BUFFER = 500
PER_TICK = 50
TARGET = "brain_timeline"


def to_cloud_event(event: dict[str, Any]) -> dict[str, Any]:
    data = {"message": event["message"], **event["data"]}
    subject = data.get("incident_id") or (data.get("result") or {}).get("incident_id")
    return {"specversion": "1.0", "id": f"twin-{uuid.uuid4().hex[:16]}", "source": "twin", "type": f"twin.{event['kind']}",
            "time": event["ts"], **({"subject": str(subject)} if subject else {}), "datacontenttype": "application/json", "data": data}


class BrainTimeline:
    def __init__(self, url: str, token: str, events: EventLog) -> None:
        self.url, self.token, self.events = url, token, events
        self._waiting: deque[dict[str, Any]] = deque(maxlen=BUFFER)
        self._down = False
        if url:
            events.add_listener(self._notice)

    def _notice(self, event: dict[str, Any]) -> None:
        if event["kind"].startswith(GROUND_TRUTH_PREFIX) or event["kind"] in NOISE or event["data"].get("target") == TARGET:
            return
        self._waiting.append(event)

    async def flush(self, client: httpx.AsyncClient) -> None:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        for _ in range(min(PER_TICK, len(self._waiting))):
            try:
                resp = await client.post(self.url, json=to_cloud_event(self._waiting[0]), headers=headers)
            except httpx.HTTPError as exc:
                return self._failed(f"{type(exc).__name__}: {exc}")
            if resp.status_code >= 500:
                return self._failed(f"HTTP {resp.status_code}")
            if resp.status_code >= 400:     # refused for what it is, not for the moment: sending it again would not help
                self._failed(f"HTTP {resp.status_code}: {resp.text[:200]}")
            else:
                self._down = False
            self._waiting.popleft()

    def _failed(self, error: str) -> None:
        if not self._down:
            self._down = True
            self.events.emit("delivery_failed", f"city brain timeline did not take our events: {error}"[:300], target=TARGET, error=error[:200])
