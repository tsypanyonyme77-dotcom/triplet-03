"""Audit logger: every event goes to ${LOG_DIR}/t5-guardian-<YYYYMMDD>.log as one JSON line and to the timeline."""

from __future__ import annotations

import contextvars
import json
import secrets
from pathlib import Path
from typing import IO, Any

import structlog

from guardian.adapters.schemas import AuditEventOut
from guardian.audit.timeline_emitter import TimelineEmitter
from guardian.clock import Clock
from guardian.models import AuditEvent

scenario_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar("scenario_id", default=None)
log = structlog.get_logger("guardian")


class AuditLogger:
    def __init__(self, log_dir: str | Path, prefix: str, clock: Clock, emitter: TimelineEmitter) -> None:
        self.dir = Path(log_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.prefix = prefix
        self.clock = clock
        self.emitter = emitter
        self._fh: IO[str] | None = None
        self._day = ""

    def path_for_today(self) -> Path:
        return self.dir / f"{self.prefix}-{self.clock.now():%Y%m%d}.log"

    def _file(self) -> IO[str]:
        day = f"{self.clock.now():%Y%m%d}"
        if self._fh is None or day != self._day:
            if self._fh:
                self._fh.close()
            self._day = day
            self._fh = self.path_for_today().open("a", encoding="utf-8")
        return self._fh

    def emit(self, type_: str, summary: str, **fields: Any) -> AuditEvent:
        """Never raises: an audit failure is logged to stderr and the pipeline continues."""
        event = AuditEvent(
            event_id=f"evt-{secrets.token_hex(6)}",
            ts=self.clock.now(),
            type=type_,
            scenario_id=fields.pop("scenario_id", None) or scenario_id_var.get(),
            summary=summary,
            sensor_id=fields.pop("sensor_id", None),
            actuator_id=fields.pop("actuator_id", None),
            zone_id=fields.pop("zone_id", None),
            data=fields.pop("data", None) or fields,
        )
        wire = AuditEventOut.from_event(event).model_dump()
        try:
            fh = self._file()
            fh.write(json.dumps(wire, default=str) + "\n")
            fh.flush()
        except OSError as e:
            log.error("audit_write_failed", error=str(e))
        self.emitter.publish("timeline", wire)
        return event

    def close(self) -> None:
        if self._fh:
            self._fh.close()
            self._fh = None
