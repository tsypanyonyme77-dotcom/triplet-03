"""The clock and the id source: real by default, repeatable when a run asks for it.

Everything that stamps an event or names a thing (an event id, an approval id, "now" for a verdict's expiry) asks here, so
a run that must be repeatable can replace both. A live run uses the system clock and random ids. A deterministic run
(`--deterministic`) starts at a fixed epoch, moves forward only as readings arrive (so an event is stamped with the time of
the reading that caused it), and numbers its ids. Two such runs of one input give the same bytes.

One clock is current at a time, held in a module variable rather than a context variable: the Twin and Guardian stand-ins
answer from tasks the run did not start, and they must see the same clock.
"""

from __future__ import annotations

import uuid
from collections import Counter
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...

    def new_id(self, kind: str) -> str: ...

    deterministic: bool

    def observe(self, moment: datetime) -> None:
        """A reading stamped `moment` has arrived. A real clock ignores this; a deterministic one moves forward to it."""
        ...


class SystemClock:
    deterministic = False

    def now(self) -> datetime:
        return datetime.now(UTC)

    def new_id(self, kind: str) -> str:
        return str(uuid.uuid4())

    def observe(self, moment: datetime) -> None:
        return None


class DeterministicClock:
    deterministic = True  # a repeatable run records no measured durations: they are the one thing that cannot repeat

    def __init__(self, epoch: datetime) -> None:
        self.epoch = epoch
        self._now = epoch
        self._counts: Counter[str] = Counter()

    def now(self) -> datetime:
        return self._now

    def advance_to(self, offset_s: float) -> None:
        self._now = self.epoch + timedelta(seconds=offset_s)

    def observe(self, moment: datetime) -> None:
        self._now = max(self._now, moment)

    def new_id(self, kind: str) -> str:
        self._counts[kind] += 1
        return f"{kind}-{self._counts[kind]:06d}"


_current: Clock = SystemClock()


def current() -> Clock:
    return _current


@contextmanager
def use(replacement: Clock) -> Iterator[Clock]:
    """Make `replacement` the clock for the duration; the previous one comes back even if the run fails."""
    global _current
    previous, _current = _current, replacement
    try:
        yield replacement
    finally:
        _current = previous
