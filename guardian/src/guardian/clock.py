"""Injected clock. The only module allowed to read wall time or sleep, so tests run 30 s windows instantly."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...

    async def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)


class FakeClock:
    """Manual clock. `sleep` advances time and yields once, so loops stay cooperative."""

    def __init__(self, start: datetime | None = None) -> None:
        self._t = start or datetime(2026, 11, 2, 14, 0, 0, tzinfo=UTC)

    def now(self) -> datetime:
        return self._t

    def advance(self, seconds: float) -> None:
        self._t += timedelta(seconds=seconds)

    def set(self, t: datetime) -> None:
        self._t = t

    async def sleep(self, seconds: float) -> None:
        self.advance(seconds)
        await asyncio.sleep(0)


def iso(dt: datetime) -> str:
    """UTC ISO-8601 with a Z suffix, second precision unless sub-second detail exists."""
    dt = dt.astimezone(UTC)
    s = dt.isoformat(timespec="milliseconds" if dt.microsecond else "seconds")
    return s.replace("+00:00", "Z")
