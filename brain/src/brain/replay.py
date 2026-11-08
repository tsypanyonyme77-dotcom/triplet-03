"""`brain replay`: play a run's journal back into the Brain and check that it decides the same.

The journal holds every input of a run (see `brain.journal`). Replay answers the Brain's questions from it: a Twin double
releases the recorded readings in their recorded order and answers each actuator call as the Twin did; a Guardian double gives
each reading its recorded verdict (or its recorded silence). The Brain runs on the journal's own policy and models, under a
deterministic clock that starts at the journal's epoch, so a run that was deterministic replays to the same bytes.

Outputs are never replayed: only what came in. If the Brain's code or config changed, the decisions may change, and the
difference is the point: `compare` says where.
"""

from __future__ import annotations

import asyncio
import os
from collections import defaultdict, deque
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from brain import clock
from brain.config import ModelsConfig, PartnersConfig, Policy, fingerprint, secret
from brain.contracts import ActuatorCall, ActuatorResult, TrustVerdict
from brain.contracts.signing import sign
from brain.journal import Journal, JournalError, read_journal
from brain.ports import GuardianUnavailable, TwinError
from brain.repro import levels, normalise
from brain.runtime import BrainService
from brain.scenario import DEV_SECRETS
from brain.timeline import MemorySink, Timeline


class ReplayRefused(RuntimeError):
    """The journal cannot be trusted, or the config it would run under is not the one it was recorded with."""


@dataclass
class Difference:
    same: bool
    first_difference: str | None = None


class JournalTwin:
    def __init__(self, journal: Journal, twin_secret: str | None) -> None:
        self._readings = [self._envelope(r, twin_secret) for r in journal.inputs if r["kind"] == "reading"]
        self._topology = next((r["topology"] for r in journal.inputs if r["kind"] == "topology"), {})
        self._capabilities = next((r["capabilities"] for r in journal.inputs if r["kind"] == "capabilities"), {})
        self._answers: dict[tuple[str, str], deque[tuple[str, Any]]] = defaultdict(deque)
        for r in journal.inputs:
            if r["kind"] == "actuator_result":
                self._answers[(r["action"], r["actuator_id"])].append(("result", r["result"]))
            elif r["kind"] == "actuator_error":
                self._answers[(r["action"], r["actuator_id"])].append(("error", r["message"]))

    @staticmethod
    def _envelope(record: dict[str, Any], twin_secret: str | None) -> dict[str, Any]:
        envelope = record["envelope"]
        if record.get("stripped") and twin_secret:
            # The Twin sent fields the journal does not keep. Put their names back with no value, so perception drops them again and
            # reports them as it did, then sign the copy: the Twin's own signature covered what is no longer there.
            value = {**envelope["value"], **{name: None for name in record["stripped"]}}
            envelope = sign({k: v for k, v in envelope.items() if k not in ("provenance", "value")} | {"value": value}, twin_secret, "twin")
        return envelope

    async def stream_readings(self) -> AsyncIterator[dict[str, Any]]:
        for envelope in self._readings:
            yield envelope

    async def get_topology(self) -> dict[str, Any]:
        return self._topology

    async def list_capabilities(self) -> dict[str, str]:
        return self._capabilities

    async def call_actuator(self, call: ActuatorCall) -> ActuatorResult:
        queue = self._answers[(call.action, call.actuator_id)]
        if not queue:
            raise TwinError(f"{call.action} on {call.actuator_id} is not in the journal: the Brain asked for something it did not ask for then")
        kind, payload = queue.popleft()
        if kind == "error":
            raise TwinError(payload)
        return ActuatorResult.model_validate(payload)


class JournalGuardian:
    def __init__(self, journal: Journal) -> None:
        self._verdicts: dict[tuple[Any, Any], dict[str, Any] | None] = {}
        self._quarantine: dict[str, deque[bool | None]] = defaultdict(deque)
        for r in journal.inputs:
            key = (r.get("sensor_id"), r.get("sequence_no"))
            if r["kind"] == "verdict":
                self._verdicts[key] = r["verdict"]
            elif r["kind"] == "verdict_unavailable":
                self._verdicts[key] = None
            elif r["kind"] == "quarantine":
                self._quarantine[r["device_id"]].append(r["answer"])
            elif r["kind"] == "quarantine_unavailable":
                self._quarantine[r["device_id"]].append(None)

    async def get_verdict(self, reading: dict[str, Any], deadline_s: float) -> TrustVerdict:
        key = (reading.get("sensor_id"), reading.get("sequence_no"))
        if key not in self._verdicts or self._verdicts[key] is None:
            raise GuardianUnavailable(f"no verdict for {key} in the journal")
        return TrustVerdict.model_validate(self._verdicts[key])

    async def is_quarantined(self, device_id: str) -> bool:
        queue = self._quarantine[device_id]
        if not queue or queue[0] is None:
            if queue:
                queue.popleft()
            raise GuardianUnavailable(f"no answer about {device_id} in the journal")
        return bool(queue.popleft())


async def replay(path: Path, *, policy: Policy | None = None, allow_config_change: bool = False, secret_value: str | None = None) -> list[dict[str, Any]]:
    """The events the Brain emits when the journal at `path` is played back into it."""
    for name, value in DEV_SECRETS.items():
        os.environ.setdefault(name, value)
    signing = secret_value if secret_value is not None else os.environ.get("BRAIN_HMAC_SECRET", "")
    try:
        journal = read_journal(Path(path), signing)
    except JournalError as error:
        raise ReplayRefused(str(error)) from error
    header = journal.header
    if policy is not None and fingerprint(policy) != header["config_hash"] and not allow_config_change:
        raise ReplayRefused(f"the current config ({fingerprint(policy)}) differs from the one this run was recorded with ({header['config_hash']}); "
                            "pass --allow-config-change to replay under it anyway")
    used = policy if policy is not None else Policy.model_validate(header["policy"])
    models = ModelsConfig.model_validate(header["models"])
    partners = PartnersConfig()

    with clock.use(clock.DeterministicClock(datetime.fromisoformat(header["epoch"]))):
        sink = MemorySink()
        timeline = Timeline([sink])
        service = BrainService(partners, used, JournalTwin(journal, secret(partners.twin.hmac_secret_env)), JournalGuardian(journal), timeline, models)
        timeline.emit("brain.scenario.started", header["scenario"], {"name": header.get("name"), "speed": header.get("speed")})
        await service.start()
        await asyncio.wait_for(service.run_until_quiet(), 30)
    return [event.model_dump(mode="json") for event in sink.events]


def _clean(event: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in normalise(event).items() if value is not None}


def compare(replayed: list[dict[str, Any]], recorded: list[dict[str, Any]]) -> Difference:
    """Do the two runs decide and emit the same? The scenario runner's own events are left out: they are not the Brain's."""
    ours = [_clean(e) for e in replayed if not e["type"].startswith("brain.scenario.")]
    theirs = [_clean(e) for e in recorded if not e["type"].startswith("brain.scenario.")]
    by_name = {level.name: level for level in levels([ours, theirs])}
    if by_name["decisions"].identical and by_name["stream"].identical:
        return Difference(True)
    return Difference(False, by_name["stream"].first_difference or "the decisions differ")
