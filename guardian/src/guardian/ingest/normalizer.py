"""Envelope → internal Reading. Coerces int to float for float fields so detectors see one numeric type."""

from __future__ import annotations

from guardian.adapters.schemas import Envelope
from guardian.config import SensorRegistry
from guardian.models import Reading


def normalize(env: Envelope, registry: SensorRegistry, source: str = "twin") -> Reading:
    reading = env.to_reading(source)
    fields = registry.sensor_types[reading.sensor_type].fields
    for name, fs in fields.items():
        if fs.type == "float":
            reading.value[name] = float(reading.value[name])
    return reading
