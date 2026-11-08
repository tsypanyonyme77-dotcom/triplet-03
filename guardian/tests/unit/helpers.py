"""Small builders for unit tests."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from guardian.clock import FakeClock
from guardian.models import LayerResult, Reading

T0 = FakeClock().now()


def reading(sensor_id: str = "wl-port-03", sensor_type: str = "water_level", zone_id: str = "zone-07",
            value: dict[str, Any] | None = None, seq: int = 1, ts: datetime | None = None,
            dt: float = 0.0, **kw: Any) -> Reading:
    return Reading(sensor_id=sensor_id, sensor_type=sensor_type, zone_id=zone_id,
                   ts=(ts or T0) + timedelta(seconds=dt), sequence_no=seq,
                   value=value if value is not None else {"level_m": 0.4}, **kw)


def lr(layer: str, passed: bool = True, severity: str = "info", reason: str | None = None) -> LayerResult:
    return LayerResult(layer=layer, passed=passed, severity=severity, reason_code=reason)  # type: ignore[arg-type]
