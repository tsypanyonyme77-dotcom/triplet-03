"""An in-process bus for typed messages.

Delivery is ordered and complete before `publish` returns, so a scenario run gives the same
decisions every time. Regions of the Brain talk through it instead of calling each other.
"""

from __future__ import annotations

import inspect
import logging
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel

from brain.contracts import SensorReading, TrustVerdict

log = logging.getLogger("brain.mind")


@dataclass(frozen=True)
class Percept:
    """One reading, parsed, with the Guardian's verdict on it. Published as soon as it is stored."""

    reading: SensorReading
    value: BaseModel | None
    verdict: TrustVerdict
    trace_id: str


@dataclass(frozen=True)
class IncidentTouched:
    """Triage found new evidence for these incidents (or opened them)."""

    incident_ids: tuple[str, ...]
    trace_id: str | None
    at: datetime | None = None  # when the triggering reading was taken: the city's clock, not the laptop's


@dataclass(frozen=True)
class IncidentClosed:
    incident_id: str
    outcome: str
    trace_id: str | None


class Bus:
    def __init__(self) -> None:
        self._handlers: dict[type, list[Callable[[Any], Awaitable[None] | None]]] = defaultdict(list)

    def subscribe[M](self, message_type: type[M], handler: Callable[[M], Awaitable[None] | None]) -> None:
        self._handlers[message_type].append(handler)

    async def publish(self, message: object) -> None:
        for handler in list(self._handlers[type(message)]):
            try:
                result = handler(message)
                if inspect.isawaitable(result):
                    await result
            except Exception:  # one region failing must not stop the others hearing the message
                log.exception("handler %r failed on %s", handler, type(message).__name__)
