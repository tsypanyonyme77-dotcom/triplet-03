"""The input journal: everything a run received from outside, written as it arrived, chained and sealed.

The timeline log says what the Brain did; it holds a summary of each reading, not the reading. The journal holds the other half,
the inputs: every raw reading envelope exactly as the Twin sent it (before perception, so a rejected reading is kept too), the
Guardian's verdict for each (or that it was silent), its answers about quarantine, the Twin's topology and capabilities, and the
Twin's answer to every actuator call. With the policy and the clock in its header, that is all a rerun needs (`brain replay`).

Lines are chained with the same `prevhash` and `hash` fields as the timeline; the last line seals the chain with an HMAC under the
Brain's signing secret, so a journal cannot be rewritten without that secret. `read_journal` and `brain replay` check both.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from brain.contracts import ActuatorCall, ActuatorResult, TrustVerdict
from brain.ports import GuardianUnavailable, TwinError
from brain.timeline import GENESIS, _chain_hash

# Names that never enter a journal even when a rejected reading never reached perception's own allowlist.
DEMOGRAPHIC = frozenset({"age", "gender", "sex", "ethnicity", "race", "nationality", "religion", "income", "wealth", "occupation", "education", "marital_status", "disability"})


def reading_record(raw: dict[str, Any], dropped: list[str]) -> dict[str, Any]:
    """The journal's copy of one raw reading: as received, without the fields perception dropped or any demographic name.

    The Twin's signature covered those fields, so it no longer covers this copy; it is kept as `original_hmac`, and a replay
    signs the copy again with the shared secret."""
    envelope = json.loads(json.dumps(raw, default=str))
    value = envelope.get("value")
    stripped: list[str] = []
    if isinstance(value, dict):
        for name in sorted({*dropped, *DEMOGRAPHIC} & set(value)):
            del value[name]
            stripped.append(name)
    record: dict[str, Any] = {"envelope": envelope, "stripped": stripped}
    if stripped:
        record["original_hmac"] = (raw.get("provenance") or {}).get("hmac")
    return record


class JournalError(ValueError):
    """The journal cannot be trusted: a line was changed, the chain is broken, or the seal does not match."""


@dataclass
class Journal:
    header: dict[str, Any]
    inputs: list[dict[str, Any]]
    sealed: bool


def _seal(last_hash: str, secret: str) -> str:
    return hmac.new(secret.encode(), last_hash.encode(), hashlib.sha256).hexdigest()


class JournalWriter:
    def __init__(self, path: Path, header: dict[str, Any], secret: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._file = path.open("w", encoding="utf-8")
        self._prev = GENESIS
        self._count = 0
        self._secret = secret
        self._write({"kind": "header", **header})

    def append(self, kind: str, **fields: Any) -> None:
        self._count += 1
        self._write({"kind": kind, "seq": self._count, **fields})

    def _write(self, record: dict[str, Any]) -> None:
        record["prevhash"] = self._prev
        self._prev = record["hash"] = _chain_hash(self._prev, record)
        self._file.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        self._file.flush()

    def close(self) -> None:
        if self._file.closed:
            return
        self._write({"kind": "seal", "records": self._count, "hmac": _seal(self._prev, self._secret)})
        self._file.close()


def read_journal(path: Path, secret: str | None = None) -> Journal:
    """The records of a journal, after checking the chain line by line and, when a secret is given, the seal."""
    prev, header, inputs, sealed, last = GENESIS, None, [], False, GENESIS
    with path.open(encoding="utf-8") as file:
        for number, line in enumerate(file, start=1):
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise JournalError(f"line {number}: not valid JSON ({error.msg})") from error
            claimed = record.pop("hash", None)
            if record.get("prevhash") != prev:
                raise JournalError(f"line {number}: prevhash does not match the previous record")
            if _chain_hash(prev, record) != claimed:
                raise JournalError(f"line {number}: record was modified")
            prev = claimed
            record.pop("prevhash", None)
            kind = record.get("kind")
            if number == 1:
                if kind != "header":
                    raise JournalError("line 1: a journal starts with its header")
                header = record
            elif kind == "seal":
                sealed = True
                if secret is not None and not hmac.compare_digest(record.get("hmac", ""), _seal(last, secret)):
                    raise JournalError(f"line {number}: the seal does not match this secret")
            else:
                inputs.append(record)
            last = claimed
    if header is None:
        raise JournalError("the journal is empty")
    if secret is not None and not sealed:
        raise JournalError("the journal has no seal: the run did not finish, or the end was cut off")
    return Journal(header, inputs, sealed)


class JournalingTwin:
    """A TwinPort that passes everything through and writes what came in to the journal."""

    def __init__(self, inner: Any, writer: JournalWriter) -> None:
        self._inner, self._writer = inner, writer

    def __getattr__(self, name: str) -> Any:  # position, resume and anything else the adapter offers
        return getattr(self._inner, name)

    async def stream_readings(self) -> AsyncIterator[dict[str, Any]]:
        # Readings are journalled by the runtime, after perception has said which fields it drops.
        async for raw in self._inner.stream_readings():
            yield raw

    async def get_topology(self) -> dict[str, Any]:
        topology = await self._inner.get_topology()
        self._writer.append("topology", topology=topology)
        return topology

    async def list_capabilities(self) -> dict[str, str]:
        capabilities = await self._inner.list_capabilities()
        self._writer.append("capabilities", capabilities=capabilities)
        return capabilities

    async def call_actuator(self, call: ActuatorCall) -> ActuatorResult:
        try:
            result = await self._inner.call_actuator(call)
        except TwinError as error:
            self._writer.append("actuator_error", action=call.action, actuator_id=call.actuator_id, message=str(error))
            raise
        self._writer.append("actuator_result", action=call.action, actuator_id=call.actuator_id, result=result.model_dump(mode="json"))
        return result


class JournalingGuardian:
    """A GuardianPort that passes everything through and writes the Guardian's answers, and its silences, to the journal."""

    def __init__(self, inner: Any, writer: JournalWriter) -> None:
        self._inner, self._writer = inner, writer

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    async def get_verdict(self, reading: dict[str, Any], deadline_s: float) -> TrustVerdict:
        ref = {"sensor_id": reading.get("sensor_id"), "sequence_no": reading.get("sequence_no")}
        try:
            verdict = await self._inner.get_verdict(reading, deadline_s)
        except GuardianUnavailable as error:
            self._writer.append("verdict_unavailable", **ref, message=str(error))
            raise
        self._writer.append("verdict", **ref, verdict=verdict.model_dump(mode="json"))
        return verdict

    async def is_quarantined(self, device_id: str) -> bool:
        try:
            answer = await self._inner.is_quarantined(device_id)
        except GuardianUnavailable as error:
            self._writer.append("quarantine_unavailable", device_id=device_id, message=str(error))
            raise
        self._writer.append("quarantine", device_id=device_id, answer=answer)
        return answer
