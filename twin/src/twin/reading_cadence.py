"""How often each sensor reports. The city offers every reading on every tick; a real sensor has an interval, and
the partners count on it: the Guardian's registry expects each type at its interval (and calls a sensor stale
after twice that), and the City Brain asks for a verdict on every reading it pulls, so a feed faster than it can
judge leaves it behind until its verdicts expire.

Event-driven readings (emergency calls, unit status) are not listed and always go out. A sensor reports
at once the first time, then at its interval; the reading that ends a fire is never held back.
"""
from __future__ import annotations

from typing import Any

# seconds; the Guardian's sensor registry where it has the type, the same as a water level for the alarms
DEFAULT_INTERVALS: dict[str, float] = {"traffic_camera": 10.0, "air_quality": 10.0, "rainfall": 10.0, "water_level": 5.0,
                                       "cctv_anomaly": 5.0, "building_fire": 5.0}


def parse_intervals(text: str) -> dict[str, float]:
    """`type=seconds,type=seconds`, from TWIN_READING_INTERVALS."""
    out: dict[str, float] = {}
    for item in (i.strip() for i in text.split(",")):
        if not item:
            continue
        kind, _, seconds = item.partition("=")
        try:
            value = float(seconds)
        except ValueError:
            value = -1.0
        if not kind.strip() or value <= 0:
            raise ValueError(f"TWIN_READING_INTERVALS: {item!r} must be <type>=<seconds above 0>")
        out[kind.strip()] = value
    return out


class ReadingCadence:
    def __init__(self, intervals: dict[str, float], tick_s: float) -> None:
        self.intervals, self.tick_s = intervals, tick_s
        self._tick = 0
        self._last: dict[str, int] = {}   # sensor id -> the tick it last reported

    def next_tick(self) -> None:
        self._tick += 1

    def due(self, spec: dict[str, Any]) -> bool:
        interval = self.intervals.get(spec["type"])
        if interval is None or (spec["type"] == "building_fire" and spec["value"].get("smoke_detected") is False):
            return True
        last = self._last.get(spec["sensor_id"])
        if last is not None and (self._tick - last) * self.tick_s < interval:
            return False
        self._last[spec["sensor_id"]] = self._tick
        return True
