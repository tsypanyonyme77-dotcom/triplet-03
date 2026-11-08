"""Which devices the Guardian has cut off. The Twin keeps simulating a quarantined sensor but stops
sending its readings, until the quarantine is cleared or a new run starts."""
from __future__ import annotations

from typing import Any


class DeviceRegistry:
    def __init__(self) -> None:
        self._blocked: dict[str, dict[str, Any]] = {}

    def block(self, device_id: str, mode: str, reason: str) -> bool:
        """False when the device is already blocked the same way (idempotent)."""
        old = self._blocked.get(device_id)
        if old and old["mode"] == mode:
            return False
        self._blocked[device_id] = {"device_id": device_id, "mode": mode, "reason": reason}
        return True

    def clear(self, device_id: str) -> bool:
        return self._blocked.pop(device_id, None) is not None

    def clear_all(self) -> None:
        self._blocked.clear()

    def blocks(self, sensor_id: str) -> bool:
        """A device covers its own sensor and the ones named after it (cam-n2 covers cam-n2-cctv)."""
        return any(sensor_id == d or sensor_id.startswith(f"{d}-") for d in self._blocked)

    def list(self) -> list[dict[str, Any]]:
        return list(self._blocked.values())
