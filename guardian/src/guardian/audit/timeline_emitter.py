"""Fan-out of events to WebSocket subscribers. Two channels: `verdicts` (Brain) and `timeline` (R3 screen)."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

CHANNELS = ("verdicts", "timeline")


class TimelineEmitter:
    def __init__(self, queue_size: int = 1000) -> None:
        self._subs: dict[str, set[asyncio.Queue[dict[str, Any]]]] = {c: set() for c in CHANNELS}
        self._size = queue_size

    def subscribe(self, channel: str) -> asyncio.Queue[dict[str, Any]]:
        q: asyncio.Queue[dict[str, Any]] = asyncio.Queue(self._size)
        self._subs[channel].add(q)
        return q

    def unsubscribe(self, channel: str, q: asyncio.Queue[dict[str, Any]]) -> None:
        self._subs[channel].discard(q)

    def subscribers(self, channel: str) -> int:
        return len(self._subs[channel])

    def publish(self, channel: str, message: dict[str, Any]) -> None:
        for q in list(self._subs[channel]):
            if q.full():  # slow consumer: drop its oldest message, never block the pipeline
                with contextlib.suppress(asyncio.QueueEmpty):
                    q.get_nowait()
            q.put_nowait(message)
