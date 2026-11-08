"""Timeline events: emitted once, fanned out to sinks (log file, console, tests, later SSE).

The JSONL sink is also the audit log: every record carries the hash of the previous
record, so removing or editing a line breaks the chain.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, TextIO

from brain import clock
from brain.contracts import TimelineEvent
from brain.contracts.signing import canonical_json
from brain.ports import TimelineSink

GENESIS = "0" * 64


class Timeline:
    def __init__(self, sinks: list[TimelineSink] | None = None) -> None:
        self.sinks: list[TimelineSink] = list(sinks or [])

    def emit(
        self,
        type: str,
        subject: str | None = None,
        data: dict[str, Any] | None = None,
        trace_id: str | None = None,
        timing: dict[str, float] | None = None,
    ) -> TimelineEvent:
        # A copy: an event is a fact at the moment it is emitted. Without it an incident's evidence list, still growing, would change
        # under a sink that keeps events in memory, while the log file (written at once) kept the earlier picture.
        event = TimelineEvent(type=type, subject=subject, traceid=trace_id, data=copy.deepcopy(data) if data else {},
                              timing=None if clock.current().deterministic else timing)
        for sink in self.sinks:
            sink.write(event)
        return event


class MemorySink:
    def __init__(self) -> None:
        self.events: list[TimelineEvent] = []

    def write(self, event: TimelineEvent) -> None:
        self.events.append(event)

    def types(self) -> list[str]:
        return [e.type for e in self.events]

    def of(self, type: str) -> list[TimelineEvent]:
        return [e for e in self.events if e.type == type]


def _chain_hash(prev: str, record: dict[str, Any]) -> str:
    return hashlib.sha256(prev.encode() + canonical_json(record)).hexdigest()


def read_log(path: Path) -> list[dict[str, Any]]:
    """The complete records of a log file. A last line cut short by a crash is left out."""
    records = []
    with path.open(encoding="utf-8") as file:
        for line in file:
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                break
    return records


class JsonlSink:
    def __init__(self, path: Path, resume: bool = False) -> None:
        """`resume` continues an existing log after a restart, chained to its last complete record."""
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._prev = GENESIS
        kept = read_log(path) if resume and path.exists() else []
        self._file = path.open("w", encoding="utf-8")
        for record in kept:
            self._file.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._prev = record["hash"]
        self._count = len(kept)
        self._file.flush()

    def write(self, event: TimelineEvent) -> None:
        record = event.model_dump(mode="json", exclude_none=True)
        record["prevhash"] = self._prev
        self._prev = record["hash"] = _chain_hash(self._prev, record)
        self._count += 1
        self._file.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()
        secret = os.environ.get("BRAIN_HMAC_SECRET")
        if secret and self._count:  # the hash chain alone can be rewritten end to end by anyone; the signed head cannot
            write_head(self.path, self._count, self._prev, secret)


def head_path(path: Path) -> Path:
    return path.with_name(path.name + ".head")


def write_head(path: Path, seq: int, tip: str, secret: str) -> None:
    """`<log>.head`: how many records the log has and the hash of the last, signed with the Brain's key. Copy it somewhere the Brain cannot write."""
    from brain.contracts.signing import sign

    head = sign({"seq": seq, "hash": tip, "time": clock.current().now().isoformat().replace("+00:00", "Z")}, secret, signed_by="city_brain")
    head_path(path).write_text(json.dumps(head, sort_keys=True) + "\n", encoding="utf-8")


def verify_head(path: Path, secret: str | None) -> tuple[str, str]:
    """('ok' | 'missing' | 'invalid' | 'mismatch', message). A missing head is not a failure: older logs have none."""
    from brain.contracts.signing import verify

    where = head_path(path)
    if not where.exists():
        return "missing", "no signed head (an older log, or the Brain had no signing key)"
    head = json.loads(where.read_text(encoding="utf-8"))
    if not secret or not verify(head, secret):
        return "invalid", "the head's signature does not match: it was not written by the Brain's key"
    lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    tip = json.loads(lines[-1])["hash"] if lines else GENESIS
    if head["seq"] != len(lines) or head["hash"] != tip:
        return "mismatch", f"the head signs {head['seq']} records ending {head['hash'][:12]}, but the log has {len(lines)} ending {tip[:12]}"
    return "ok", f"head signed for {head['seq']} records"


def verify_chain(path: Path) -> tuple[bool, str]:
    """Recompute the hash chain of a log file. Returns (ok, message)."""
    prev = GENESIS
    count = 0
    with path.open(encoding="utf-8") as file:
        for count, line in enumerate(file, start=1):
            record = json.loads(line)
            claimed = record.pop("hash", None)
            if record.get("prevhash") != prev:
                return False, f"line {count}: prevhash does not match the previous record"
            if _chain_hash(prev, record) != claimed:
                return False, f"line {count}: record was modified"
            prev = claimed
    return True, f"{count} records, chain intact"


class ConsoleSink:
    """One line per event, for a human watching a scenario run."""

    QUIET = {"brain.reading.received", "brain.verdict.received"}

    def __init__(self, stream: TextIO | None = None, verbose: bool = False) -> None:
        self.stream = stream or sys.stdout
        self.verbose = verbose

    def write(self, event: TimelineEvent) -> None:
        if not self.verbose and event.type in self.QUIET:
            return
        clock = event.time.strftime("%H:%M:%S.%f")[:-3]
        detail = json.dumps(event.data, ensure_ascii=False, default=str)
        if len(detail) > 220:
            detail = detail[:217] + "..."
        print(f"{clock}  {event.type:<28} {event.subject or '-':<18} {detail}", file=self.stream, flush=True)
