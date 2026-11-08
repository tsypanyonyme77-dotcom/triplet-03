"""Mock Guardian: returns scripted trust verdicts.

A stand-in for the Guardian layer. Verdicts come from the scenario's `guardian` block
(a default and per-sensor overrides), plus one real check: a bad HMAC is always untrusted.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from brain.contracts import utcnow
from brain.contracts.signing import verify


class MockGuardian:
    def __init__(self, twin_secret: str | None = None) -> None:
        self.twin_secret = twin_secret
        self.default = "trusted"
        self.overrides: dict[str, str] = {}
        self.down = False
        self.quarantined: set[str] = set()
        self._counter = 0

    def configure(self, default: str = "trusted", overrides: dict[str, str] | None = None, down: bool = False,
                  quarantined: list[str] | None = None) -> dict[str, Any]:
        self.default, self.overrides, self.down = default, dict(overrides or {}), down
        self.quarantined = set(quarantined or [])
        return {"default": self.default, "overrides": self.overrides, "down": self.down, "quarantined": sorted(self.quarantined)}

    def verdict(self, reading: dict[str, Any]) -> dict[str, Any]:
        self._counter += 1
        status = self.overrides.get(reading.get("sensor_id", ""), self.default)
        reasons = [f"scripted:{status}"]
        if self.twin_secret and not verify(reading, self.twin_secret):
            status, reasons = "untrusted", ["hmac_mismatch"]
        now = utcnow()
        return {
            "verdict_id": f"verdict-{self._counter:06d}",
            "reading_ref": {"sensor_id": reading.get("sensor_id"), "sequence_no": reading.get("sequence_no")},
            "status": status,
            "confidence": 0.97 if status == "trusted" else 0.9,
            "reasons": reasons,
            "issued_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=120)).isoformat(),
        }
