"""Event log: in-memory ring buffer + optional NDJSON file. Feeds the timeline screen (R3) and scenario logs (R2)."""
from __future__ import annotations

import json
import logging
from collections import deque
from pathlib import Path
from typing import Any, Callable

from twin.contract import now_iso

log = logging.getLogger("twin.events")


GROUND_TRUTH_PREFIX = "sim_"


class EventLog:
    def __init__(self, layer: str, log_dir: str = "", maxlen: int = 1000) -> None:
        self.layer = layer
        self._events: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._file: Path | None = None
        self._file_failed = False  # report a failing log file once, not on every event
        self._listeners: list[Callable[[dict[str, Any]], None]] = []
        if log_dir:
            Path(log_dir).mkdir(parents=True, exist_ok=True)
            self._file = Path(log_dir) / f"{layer}.ndjson"

    def add_listener(self, listener: Callable[[dict[str, Any]], None]) -> None:
        """Called with every event as it is emitted (it must not raise or block)."""
        self._listeners.append(listener)

    def emit(self, kind: str, message: str, **data: Any) -> dict[str, Any]:
        event = {"ts": now_iso(), "layer": self.layer, "kind": kind, "message": message, "data": data}
        self._events.append(event)
        for listener in self._listeners:
            listener(event)
        if self._file:
            try:
                with self._file.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(event, ensure_ascii=False) + "\n")
            except OSError as exc:  # a locked or full log must not take the clock or the API down with it
                if not self._file_failed:
                    log.error("cannot write %s: %s (events stay in memory, GET /events)", self._file, exc)
                self._file_failed = True
            else:
                self._file_failed = False
        return event

    def recent(self, limit: int = 200) -> list[dict[str, Any]]:
        return list(self._events)[-limit:]

    def public(self, limit: int = 200) -> list[dict[str, Any]]:
        """What another layer may read: everything but the engine's ground truth (sim_* events)."""
        return [e for e in self._events if not e["kind"].startswith(GROUND_TRUTH_PREFIX)][-limit:]
