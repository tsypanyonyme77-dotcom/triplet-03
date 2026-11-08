"""Security alerts to the Brain (WS /v1/ws/verdicts) and the timeline, with a recent-alert buffer for GET."""

from __future__ import annotations

import secrets
from collections import deque
from datetime import datetime
from typing import Any

from guardian.adapters.schemas import AlertOut
from guardian.audit.logger import AuditLogger
from guardian.audit.timeline_emitter import TimelineEmitter
from guardian.clock import Clock
from guardian.models import Alert
from guardian.threat.threat_level import ThreatLevels


class AlertBus:
    def __init__(self, clock: Clock, emitter: TimelineEmitter, audit: AuditLogger, levels: ThreatLevels) -> None:
        self.clock, self.emitter, self.audit, self.levels = clock, emitter, audit, levels
        self.recent: deque[Alert] = deque(maxlen=1000)

    def raise_alert(self, type_: str, zone_id: str | None, evidence: list[dict[str, Any]],
                    suggested_response: str, **ids: Any) -> Alert:
        alert = Alert(alert_id=f"alert-{secrets.token_hex(5)}", type=type_, zone_id=zone_id,
                      evidence=evidence[:20], suggested_response=suggested_response,
                      threat_level=self.levels.get(zone_id), ts=self.clock.now())
        self.recent.append(alert)
        wire = AlertOut.from_alert(alert).model_dump()
        self.emitter.publish("verdicts", {"type": "alert", "alert": wire})
        self.audit.emit("alert", f"{type_}: {suggested_response}", zone_id=zone_id, **ids,
                        data={"kind": type_, "alert": wire})
        return alert

    def since(self, ts: datetime | None) -> list[Alert]:
        return [a for a in self.recent if ts is None or a.ts >= ts]
