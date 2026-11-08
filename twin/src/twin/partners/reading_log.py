"""Readings by cursor, for a partner that polls (the City Brain's `list_readings(cursor, limit)`).

The cursor is the absolute position in this process's stream: reading n is the (n+1)th one emitted.
A reader keeps its cursor and asks for what comes after (the City Brain's adapter counts the readings it
received rather than reading `next_cursor`, which is why the cursor is absolute and never renumbered).
`stream_id` is new for every process, so a reader that saved a cursor sees that the Twin restarted (its
sequence numbers start again) instead of taking the new readings for replays. The log keeps the newest
`capacity` readings; a cursor older than that resumes at the oldest one kept, and a reader that counts
will then ask again for some it has (they arrive as replays, which it refuses).
"""
from __future__ import annotations

import uuid
from collections import deque
from typing import Any

DEFAULT_CAPACITY = 50_000   # about half an hour of the two-block city at one tick per second
MAX_PAGE = 1000


class ReadingLog:
    def __init__(self, capacity: int = DEFAULT_CAPACITY, stream_id: str | None = None) -> None:
        self.stream_id = stream_id or f"twin-{uuid.uuid4().hex[:12]}"
        self._kept: deque[dict[str, Any]] = deque(maxlen=capacity)
        self._first = 0   # absolute position of self._kept[0]

    @property
    def end(self) -> int:
        """The cursor after the newest reading."""
        return self._first + len(self._kept)

    def append(self, reading: dict[str, Any]) -> None:
        if len(self._kept) == self._kept.maxlen:
            self._first += 1
        self._kept.append(reading)

    def page(self, cursor: int = 0, limit: int = 200) -> dict[str, Any]:
        """Up to `limit` readings from `cursor` on, oldest first, with the cursor to ask from next."""
        if cursor < 0 or limit < 0:
            raise ValueError("cursor and limit must be 0 or more")
        start = max(cursor, self._first)
        stop = max(start, min(self.end, start + min(limit, MAX_PAGE)))
        readings = [self._kept[i - self._first] for i in range(start, stop)]
        return {"readings": readings, "next_cursor": stop, "stream_id": self.stream_id}
