"""The three interfaces the Brain's logic talks to. Partner protocols live behind them
in `brain.adapters`, so changing a partner means changing an adapter and a config file."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol

from brain.contracts import ActuatorCall, ActuatorResult, TimelineEvent, TrustVerdict


class TwinError(RuntimeError):
    pass


class GuardianUnavailable(RuntimeError):
    pass


class TwinPort(Protocol):
    def stream_readings(self) -> AsyncIterator[dict[str, Any]]:
        """Raw reading envelopes, in the order the Twin produced them."""
        ...

    async def call_actuator(self, call: ActuatorCall) -> ActuatorResult: ...

    async def get_topology(self) -> dict[str, Any]: ...

    async def list_capabilities(self) -> dict[str, str]:
        """The actuator actions the Twin really exposes: name -> description."""
        ...


class GuardianPort(Protocol):
    async def get_verdict(self, reading: dict[str, Any], deadline_s: float) -> TrustVerdict:
        """Raises GuardianUnavailable when no verdict arrives within the deadline."""
        ...

    async def is_quarantined(self, device_id: str) -> bool:
        """Has the Guardian quarantined this device? Raises GuardianUnavailable if it cannot say."""
        ...


class TimelineSink(Protocol):
    def write(self, event: TimelineEvent) -> None: ...
