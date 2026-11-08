"""Per-zone threat level normal → elevated → under_attack, with hysteresis: one step down per quiet period."""

from __future__ import annotations

from datetime import datetime

from guardian.audit.logger import AuditLogger
from guardian.clock import Clock
from guardian.ingest.state_store import SqliteStore
from guardian.models import ThreatLevel


class ThreatLevels:
    def __init__(self, quiet_period_s: float, clock: Clock, audit: AuditLogger, db: SqliteStore) -> None:
        self.quiet, self.clock, self.audit, self.db = quiet_period_s, clock, audit, db
        self.levels: dict[str, ThreatLevel] = {
            z: ThreatLevel(v) for z, v in db.get_kv("threat_levels", {}).items()
        }
        now = clock.now()
        self.last_signal: dict[str, datetime] = {z: now for z in self.levels}

    def get(self, zone: str | None) -> ThreatLevel:
        return self.levels.get(zone or "", ThreatLevel.normal)

    def touch(self, zone: str | None) -> None:
        if zone:
            self.last_signal[zone] = self.clock.now()

    def _set(self, zone: str, level: ThreatLevel, why: str) -> None:
        old = self.get(zone)
        self.levels[zone] = level
        self.db.put_kv("threat_levels", {z: v.value for z, v in self.levels.items()})
        self.audit.emit("system", f"threat level {zone}: {old.value} → {level.value}", zone_id=zone,
                        data={"kind": "threat_level", "from": old.value, "to": level.value, "why": why})

    def raise_to(self, zone: str | None, level: ThreatLevel, why: str) -> bool:
        if not zone or level.rank <= self.get(zone).rank:
            self.touch(zone)
            return False
        self.touch(zone)
        self._set(zone, level, why)
        return True

    def tick(self) -> None:
        now = self.clock.now()
        for zone, level in list(self.levels.items()):
            if level is ThreatLevel.normal:
                continue
            if (now - self.last_signal.get(zone, now)).total_seconds() >= self.quiet:
                self._set(zone, list(ThreatLevel)[level.rank - 1], f"quiet for {self.quiet:.0f}s")
                self.last_signal[zone] = now  # next step down needs another full quiet period

    def snapshot(self) -> dict[str, str]:
        return {z: v.value for z, v in self.levels.items()}
