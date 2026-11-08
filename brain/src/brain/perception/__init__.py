"""Perception: turn untrusted bytes from the Twin into typed, checked readings.

Every rejection has a stable code and a message a partner team can act on.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, ValidationError

from brain import clock
from brain.config import FieldProfile
from brain.contracts import VALUE_MODELS, SensorReading
from brain.contracts.signing import hmac_hex, verify

# Their incident types in our emergency categories (the Data Dictionary has five; they have `accident` and `crime`).
EMERGENCY_CATEGORY = {"fire": "fire", "medical": "medical", "flood": "flood", "crime": "police", "accident": "other"}


class ContractError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class Perceived:
    reading: SensorReading
    value: BaseModel | None  # typed value when the reading type is known
    dropped_fields: list[str] = field(default_factory=list)


def _describe(error: ValidationError) -> str:
    parts = [f"{'.'.join(str(p) for p in e['loc']) or '<root>'}: {e['msg']}" for e in error.errors()]
    return "; ".join(parts)


class Perception:
    def __init__(
        self,
        accepted_versions: list[str],
        twin_secret: str | None,
        require_signature: bool = True,
        profiles: dict[str, dict[str, FieldProfile]] | None = None,
        type_aliases: dict[str, str] | None = None,
        keyring: Any = None,
        max_age_s: float | None = None,
        dialect: str = "brain",
    ) -> None:
        self.dialect = dialect
        self._last_ts: dict[str, Any] = {}  # per sensor, for `sequence_reset`: a reset is believed only when it is newer than what we saw
        self.max_age_s = max_age_s  # None: a reading's timestamp is not compared with the clock
        self.keyring = keyring  # a KeyRing with the Twin's keys: key ids, rotation, EdDSA. None: the one shared secret
        self.profiles = profiles or {}
        self.type_aliases = type_aliases or {}
        self.accepted_versions = [*accepted_versions, "1.0"] if dialect == "guardian-v1" and "1.0" not in accepted_versions else accepted_versions
        self.twin_secret = twin_secret
        self.require_signature = require_signature
        self._last_seq: dict[str, int] = {}

    def snapshot(self) -> dict[str, Any]:
        """The last sequence number seen per sensor: without it a restart would accept replays of old readings."""
        return {"last_seq": dict(self._last_seq)}

    def restore(self, saved: dict[str, Any]) -> None:
        self._last_seq = {sensor: int(seq) for sensor, seq in saved.get("last_seq", {}).items()}

    def ingest(self, raw: Any) -> Perceived:
        if not isinstance(raw, dict):
            raise ContractError("schema_invalid", f"reading must be a JSON object, got {type(raw).__name__}")

        verified, reset = False, False
        if self.dialect == "guardian-v1":
            raw, reset = self._from_guardian_v1(raw)
            verified = True
        version = raw.get("contract_version")
        if version not in self.accepted_versions:
            raise ContractError(
                "bad_contract_version",
                f"contract_version {version!r} is not supported; this Brain accepts {self.accepted_versions}",
            )

        try:
            reading = SensorReading.model_validate(raw)
        except ValidationError as error:
            raise ContractError("schema_invalid", f"reading envelope is invalid: {_describe(error)}") from error

        # The signature is checked on the raw dict: re-serialising the parsed model
        # could change byte-level details such as the timestamp format.
        if verified:
            pass  # the Guardian-contract signature was checked in `_from_guardian_v1`, on the bytes as received
        elif self.keyring is not None and self.keyring.has("twin"):
            if reading.provenance is None:
                if self.require_signature:
                    raise ContractError("signature_missing", f"{reading.reading_id}: provenance.hmac is required")
            elif (why := self.keyring.verify("twin", raw, clock.current().now())) is not None:
                raise ContractError(why, f"{reading.reading_id}: {why.replace('_', ' ')}")
        elif self.twin_secret:
            if reading.provenance is None:
                if self.require_signature:
                    raise ContractError("signature_missing", f"{reading.reading_id}: provenance.hmac is required")
            elif not verify(raw, self.twin_secret):
                raise ContractError("signature_invalid", f"{reading.reading_id}: provenance.hmac does not match the payload")

        if self.max_age_s is not None and abs(age := (clock.current().now() - reading.timestamp).total_seconds()) > self.max_age_s:
            # Before the counter moves: a stale reading must not use up a sequence number the real one still needs.
            raise ContractError("reading_stale", f"{reading.reading_id}: timestamp is {age:.0f} s from the Brain's clock, more than {self.max_age_s:.0f} s")

        last = self._last_seq.get(reading.sensor_id)
        seen = self._last_ts.get(reading.sensor_id)
        if reset and last is not None and seen is not None and reading.timestamp > seen:
            last = None  # a restarted Twin: the counter starts again, but only a reading newer than the last one we saw may say so
        if last is not None and reading.sequence_no <= last:
            raise ContractError(
                "replay_or_out_of_order",
                f"{reading.sensor_id}: sequence_no {reading.sequence_no} is not greater than the last seen ({last})",
            )
        self._last_seq[reading.sensor_id] = reading.sequence_no
        self._last_ts[reading.sensor_id] = reading.timestamp

        reading, consumed = self._translate(reading)
        model = VALUE_MODELS.get(reading.type)
        if model is None:
            return Perceived(reading, None)
        try:
            value = model.model_validate(reading.value)
        except ValidationError as error:
            raise ContractError(
                "value_invalid", f"{reading.reading_id}: value for type {reading.type!r} is invalid: {_describe(error)}"
            ) from error
        dropped = sorted(set(reading.value) - set(model.model_fields) - consumed)
        # What the Brain keeps (graph, state file, episodes) is the allowlisted value only: dropped fields are gone for good.
        return Perceived(reading.model_copy(update={"value": value.model_dump()}), value, dropped)

    def _from_guardian_v1(self, raw: Any) -> tuple[Any, bool]:
        """A reading as the Guardian team's contract 1.0 has it, in ours: check their `hmac` (HMAC-SHA256 over the sorted, compact JSON without it, as they
        document), then `sensor_type` becomes `type` and `sequence_reset` is carried out. Returns (our reading, whether it asks for a counter reset)."""
        if not isinstance(raw, dict):
            return raw, False  # the caller refuses it
        if "sensor_type" not in raw:
            raise ContractError("schema_invalid", "a reading in the Guardian contract carries sensor_type (twin.dialect: guardian-v1)")
        if self.twin_secret:
            if "hmac" not in raw:
                if self.require_signature:
                    raise ContractError("signature_missing", f"{raw.get('sensor_id')}#{raw.get('sequence_no')}: hmac is required")
            else:
                if not hmac.compare_digest(hmac_hex({k: v for k, v in raw.items() if k != "hmac"}, self.twin_secret), str(raw["hmac"])):
                    raise ContractError("signature_invalid", f"{raw.get('sensor_id')}#{raw.get('sequence_no')}: hmac does not match the payload")
        ours = {k: v for k, v in raw.items() if k not in ("hmac", "sensor_type", "sequence_reset")}
        ours["type"] = raw["sensor_type"]
        value = ours.get("value")
        if ours["type"] == "emergency_call" and isinstance(value, dict) and "category" not in value:
            ours["value"] = {"call_id": value.get("call_id"), "category": EMERGENCY_CATEGORY.get(str(value.get("incident_type")), "other")}  # caller_id is dropped: no personal data
        return ours, raw.get("sequence_reset") is True

    def _translate(self, reading: SensorReading) -> tuple[SensorReading, set[str]]:
        """Apply the type alias and the field profile. Runs only after the signature and replay checks."""
        canonical = self.type_aliases.get(reading.type, reading.type)
        value, consumed = dict(reading.value), set()
        for field_name, profile in self.profiles.get(canonical, {}).items():
            source = reading.value.get(profile.from_field)
            if field_name in value or profile.from_field not in value:
                continue
            if not isinstance(source, int | float) or isinstance(source, bool):
                raise ContractError("value_invalid", f"{reading.reading_id}: profile field {profile.from_field!r} must be a number, got {source!r}")
            value[field_name] = source * profile.scale + profile.offset
            consumed.add(profile.from_field)
        if canonical == reading.type and not consumed:
            return reading, consumed
        return reading.model_copy(update={"type": canonical, "value": value}), consumed
