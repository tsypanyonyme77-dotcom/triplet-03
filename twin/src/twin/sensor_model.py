"""What a real sensor reports, from what is really there. The city gives the truth each tick; a sensor measures
over a window, wobbles a little, and sits where it sits. The Guardian judges readings by exactly this:
its limits (guardian/config/thresholds.yaml) take a value that jumps in one tick for a spoof, and 50 identical
values for a stuck sensor. The truth stays in the engine; only what is reported changes.

  rain gauge    the mean over RAIN_WINDOW_S, so a downpour shows as a climb (limit 2 mm/h per s)
  air quality   the mean over AIR_WINDOW_S (limit 5 AQI per s), particulates alongside
  camera        the mean over CAMERA_WINDOW_S of congestion, count and speed, not each car at a red light
                (limit 0.03 congestion per s); the smoke flag is what it sees now
  water level   the water in the drain shaft at the low point: the shaft fills first, SHAFT_M by the time
                ROAD_FILL_M stands on the road, then the road's water adds to it. So a flooded street reads
                about 1.1 m, above the City Brain's flood line of 1.0 m and below the Guardian's notable 1.2 m, and
                a dry one 0. The gauge is damped, as a stilling well is, to LEVEL_RATE_M_S (limit 0.01 m/s). The depth
                on the road stays in `road_depth_m`.
Every value but a true zero wobbles by a small noise; a dry gauge reads exactly dry, which the Guardian expects.
"""
from __future__ import annotations

import random
from collections import deque
from typing import Any

RAIN_WINDOW_S, AIR_WINDOW_S, CAMERA_WINDOW_S = 90.0, 60.0, 60.0
SHAFT_M, ROAD_FILL_M = 0.8, 0.2
LEVEL_RATE_M_S = 0.008
RAIN_NOISE, AQI_NOISE, LEVEL_NOISE, FLOW_NOISE = 0.2, 1, 0.002, 0.004


def shaft_level(road_depth_m: float) -> float:
    """The water in the drain shaft, from the depth on the road."""
    if road_depth_m <= 0.0:
        return 0.0
    return SHAFT_M * min(1.0, road_depth_m / ROAD_FILL_M) + max(0.0, road_depth_m - ROAD_FILL_M)


class SensorModel:
    def __init__(self, tick_s: float, seed: int | None = None) -> None:
        self.tick_s = tick_s
        self._rng = random.Random(seed or 0)
        self._windows: dict[tuple[str, str], deque[float]] = {}
        self._levels: dict[str, float] = {}   # sensor id -> what its damped gauge stands at

    def _mean(self, sensor_id: str, field: str, value: float, window_s: float) -> float:
        samples = self._windows.setdefault((sensor_id, field), deque(maxlen=max(1, round(window_s / self.tick_s))))
        if not samples:     # a new sensor has been reading this all along, or it would seem to jump later
            samples.extend([value] * samples.maxlen)
        samples.append(value)
        return sum(samples) / len(samples)

    def _wobble(self, value: float, amplitude: float) -> float:
        return max(0.0, value + self._rng.uniform(-amplitude, amplitude)) if value > 0.0 else value

    def apply(self, spec: dict[str, Any]) -> dict[str, Any]:
        """The reading as this sensor reports it; a type with no model comes back as it is."""
        model = {"rainfall": self._rain, "air_quality": self._air, "traffic_camera": self._camera, "water_level": self._water}.get(spec["type"])
        return spec if model is None else {**spec, "value": model(spec["sensor_id"], spec["value"])}

    def _rain(self, sensor_id: str, v: dict[str, Any]) -> dict[str, Any]:
        mean = self._mean(sensor_id, "mm_per_hr", v["mm_per_hr"], RAIN_WINDOW_S)
        return {**v, "mm_per_hr": round(self._wobble(mean, RAIN_NOISE), 1) if mean >= 0.05 else 0.0}

    def _air(self, sensor_id: str, v: dict[str, Any]) -> dict[str, Any]:
        mean = self._mean(sensor_id, "aqi", v["aqi"], AIR_WINDOW_S)
        aqi = min(500, max(0, round(mean) + self._rng.randint(-AQI_NOISE, AQI_NOISE)))
        scale = aqi / v["aqi"] if v["aqi"] else 1.0
        return {**v, "aqi": aqi, **{f: round(v[f] * scale, 1) for f in ("pm25_ugm3", "pm10_ugm3") if f in v}}

    def _camera(self, sensor_id: str, v: dict[str, Any]) -> dict[str, Any]:
        mean = lambda f, w=CAMERA_WINDOW_S: self._mean(sensor_id, f, v[f], w)  # noqa: E731
        return {**v, "congestion_score": round(mean("congestion_score"), 3), "vehicle_count": round(mean("vehicle_count")),
                "avg_speed_kmh": round(mean("avg_speed_kmh"), 1)}

    def _water(self, sensor_id: str, v: dict[str, Any]) -> dict[str, Any]:
        depth, target = v["level_m"], shaft_level(v["level_m"])
        step = LEVEL_RATE_M_S * self.tick_s
        level = self._levels.get(sensor_id, target)
        level = self._levels[sensor_id] = max(level - step, min(level + step, target))
        return {**v, "level_m": round(self._wobble(level, LEVEL_NOISE), 3), "road_depth_m": depth,
                "flow_rate_m3s": round(self._wobble(v["flow_rate_m3s"], FLOW_NOISE), 3)}
