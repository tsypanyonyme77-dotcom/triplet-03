"""Envelope validation: contract_version first, then schema, then value fields against the sensor registry."""

from __future__ import annotations

import math
from typing import Any

from pydantic import ValidationError

from guardian.adapters.schemas import Envelope
from guardian.config import SensorRegistry


class IngestError(Exception):
    def __init__(self, code: str, message: str, field: str | None = None, raw: Any = None) -> None:
        super().__init__(message)
        self.code, self.message, self.field, self.raw = code, message, field, raw

    def as_dict(self) -> dict[str, Any]:
        return {"error": self.code, "message": self.message, "field": self.field}


def _check_value(sensor_type: str, value: dict[str, Any], registry: SensorRegistry) -> None:
    spec = registry.sensor_types[sensor_type]
    for name in value:
        if name not in spec.fields:
            raise IngestError("schema_invalid", f"unknown field {name!r} for sensor_type {sensor_type}",
                              f"value.{name}")
    for name, fs in spec.fields.items():
        if name not in value:
            raise IngestError("schema_invalid", f"missing field {name!r} for sensor_type {sensor_type}",
                              f"value.{name}")
        v = value[name]
        ok = {
            "int": isinstance(v, int) and not isinstance(v, bool),
            "float": isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v),
            "bool": isinstance(v, bool),
            "str": isinstance(v, str) and 0 < len(v) <= 256,
        }[fs.type]
        if not ok:
            raise IngestError("schema_invalid", f"field {name!r} must be {fs.type}, got {v!r}"[:200],
                              f"value.{name}")
        if fs.enum and v not in fs.enum:
            raise IngestError("schema_invalid", f"field {name!r} must be one of {fs.enum}", f"value.{name}")


def validate_envelope(raw: Any, registry: SensorRegistry, contract_version: str) -> Envelope:
    if not isinstance(raw, dict):
        raise IngestError("schema_invalid", "reading must be a JSON object", None, raw)
    if "contract_version" not in raw:
        raise IngestError("schema_invalid", "missing contract_version", "contract_version", raw)
    if raw["contract_version"] != contract_version:
        raise IngestError(
            "contract_version_mismatch",
            f"contract_version {raw['contract_version']!r} is not supported; this Guardian speaks "
            f"{contract_version!r}",
            "contract_version",
            raw,
        )
    try:
        env = Envelope.model_validate(raw)
    except ValidationError as e:
        err = e.errors()[0]
        loc = ".".join(str(p) for p in err["loc"]) or None
        raise IngestError("schema_invalid", f"{loc}: {err['msg']}", loc, raw) from None
    if env.sensor_type not in registry.sensor_types:
        raise IngestError("schema_invalid", f"unknown sensor_type {env.sensor_type!r}", "sensor_type", raw)
    try:
        _check_value(env.sensor_type, env.value, registry)
    except IngestError as e:
        e.raw = raw
        raise
    return env
