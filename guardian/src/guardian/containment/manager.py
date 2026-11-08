"""Containment manager: every action is persisted (SQLite), sent to the Twin as a guardian-authorised call,
and audited. Twin failures never undo local enforcement."""

from __future__ import annotations

import secrets
from collections.abc import Callable
from typing import Any

from guardian.adapters.schemas import ActuatorCallIn
from guardian.adapters.twin_client import TwinClient, TwinUnavailable
from guardian.audit.logger import AuditLogger
from guardian.clock import Clock
from guardian.config import ContainmentCfg
from guardian.containment.isolate import isolation_allowed
from guardian.containment.quarantine import cooldown_for, release_ready
from guardian.ingest.state_store import SqliteStore
from guardian.models import ActuatorCall, ContainmentRecord, Status, Verdict
from guardian.threat.alerts import AlertBus
from guardian.threat.attack_catalogue import AttackCatalogue


class ContainmentManager:
    def __init__(self, db: SqliteStore, cfg: ContainmentCfg, twin: TwinClient, clock: Clock,
                 audit: AuditLogger, alerts: AlertBus) -> None:
        self.db, self.cfg, self.twin, self.clock, self.audit, self.alerts = db, cfg, twin, clock, audit, alerts
        self.records: dict[tuple[str, str], ContainmentRecord] = {
            (r.device_id, r.kind): r for r in db.active_containment()
        }
        self.releases: dict[str, int] = db.get_kv("containment_releases", {})
        self.on_quarantine: Callable[[str], None] | None = None

    # ---------- queries
    def _active(self, device_id: str, kind: str) -> bool:
        r = self.records.get((device_id, kind))
        return bool(r and r.active)

    def is_isolated(self, device_id: str) -> bool:
        return self._active(device_id, "isolation")

    def is_quarantined(self, device_id: str) -> bool:
        return self._active(device_id, "quarantine")

    def is_unreliable(self, device_id: str) -> bool:
        return self._active(device_id, "unreliable")

    def is_contained(self, device_id: str) -> bool:
        return self.is_isolated(device_id) or self.is_quarantined(device_id)

    def contained_reason(self, device_id: str) -> str | None:
        if self.is_quarantined(device_id):
            return "device_quarantined"
        if self.is_isolated(device_id):
            return "sensor_isolated"
        return None

    def active(self) -> list[ContainmentRecord]:
        return [r for r in self.records.values() if r.active]

    def can_isolate(self, zone_id: str | None) -> bool:
        return isolation_allowed(self.records.values(), zone_id, self.cfg.max_isolations_per_zone)

    # ---------- actions
    async def _tell_twin(self, action: str, device_id: str, zone_id: str | None, justification: str) -> None:
        call = ActuatorCall(call_id=f"gcall-{secrets.token_hex(5)}", actuator_id=device_id, action=action,
                            params={"device_id": device_id}, zone_id=zone_id, requesting_layer="guardian",
                            trust_ref=None, justification=justification)
        try:
            reply = await self.twin.call_tool(action, ActuatorCallIn.from_call(call).model_dump())
            self.audit.emit("action", f"twin {action} {device_id}: {reply.get('status')}", actuator_id=device_id,
                            zone_id=zone_id, data={"kind": action, "call": call.model_dump(), "twin_reply": reply})
        except TwinUnavailable as e:
            self.audit.emit("error", f"twin {action} {device_id} failed; enforced locally only",
                            actuator_id=device_id, zone_id=zone_id, data={"kind": "twin_unreachable", "error": str(e)})

    def _record(self, r: ContainmentRecord) -> ContainmentRecord:
        self.records[(r.device_id, r.kind)] = r
        self.db.put_containment(r)
        return r

    async def isolate(self, sensor_id: str, zone_id: str | None, reason: str,
                      evidence: list[dict[str, Any]]) -> ContainmentRecord | None:
        if self.is_isolated(sensor_id):
            return self.records[(sensor_id, "isolation")]
        if not self.can_isolate(zone_id):
            self.alerts.raise_alert("isolation_cap_reached", zone_id,
                                    [{"sensor_id": sensor_id, "reason": reason}, *evidence[:5]],
                                    AttackCatalogue.suggested("isolation_cap_reached"), sensor_id=sensor_id)
            return None
        r = self._record(ContainmentRecord(
            device_id=sensor_id, kind="isolation", device_type="sensor", zone_id=zone_id, reason=reason,
            evidence=evidence[:10], since=self.clock.now(),
            cooldown_s=cooldown_for(self.cfg.cooldown_s, self.cfg.backoff_factor, self.releases.get(sensor_id, 0))))
        self.audit.emit("containment", f"isolate_sensor {sensor_id} ({reason})", sensor_id=sensor_id,
                        zone_id=zone_id, data={"kind": "isolate_sensor", "reason": reason, "evidence": evidence[:5]})
        await self._tell_twin("isolate_sensor", sensor_id, zone_id, f"guardian: {reason}")
        return r

    async def quarantine(self, device_id: str, device_type: str, reason: str, zone_id: str | None = None,
                         evidence: list[dict[str, Any]] | None = None) -> ContainmentRecord:
        if not reason:
            raise ValueError("quarantine needs a reason")
        if self.is_quarantined(device_id):
            return self.records[(device_id, "quarantine")]
        r = self._record(ContainmentRecord(
            device_id=device_id, kind="quarantine", device_type=device_type, zone_id=zone_id,
            reason=reason, evidence=(evidence or [])[:10], since=self.clock.now(),
            cooldown_s=cooldown_for(self.cfg.cooldown_s, self.cfg.backoff_factor, self.releases.get(device_id, 0))))
        self.audit.emit("containment", f"quarantine_device {device_id} ({reason})", actuator_id=device_id,
                        zone_id=zone_id, data={"kind": "quarantine_device", "device_type": device_type,
                                               "reason": reason})
        if device_type != "caller":
            await self._tell_twin("quarantine_device", device_id, zone_id, f"guardian: {reason}")
        if self.on_quarantine and device_type == "sensor":
            self.on_quarantine(device_id)
        return r

    async def flag_unreliable(self, actuator_id: str, zone_id: str | None, reason: str,
                              evidence: list[dict[str, Any]]) -> ContainmentRecord:
        r = self._record(ContainmentRecord(device_id=actuator_id, kind="unreliable", device_type="actuator",
                                           zone_id=zone_id, reason=reason, evidence=evidence[:10],
                                           since=self.clock.now()))
        self.audit.emit("containment", f"actuator {actuator_id} flagged unreliable ({reason})",
                        actuator_id=actuator_id, zone_id=zone_id, data={"kind": "flag_unreliable", "reason": reason})
        return r

    async def clear(self, device_id: str, reason: str, manual: bool = True) -> list[ContainmentRecord]:
        cleared = []
        for (dev, _kind), r in list(self.records.items()):
            if dev != device_id or not r.active:
                continue
            r.active = False
            self.db.put_containment(r)
            del self.records[(dev, _kind)]
            cleared.append(r)
        if cleared:
            self.releases[device_id] = self.releases.get(device_id, 0) + 1
            self.db.put_kv("containment_releases", self.releases)
            self.audit.emit("containment", f"clear_quarantine {device_id} ({'manual' if manual else 'auto'}: {reason})",
                            sensor_id=device_id, zone_id=cleared[0].zone_id,
                            data={"kind": "clear_quarantine", "manual": manual, "reason": reason,
                                  "cleared": [r.kind for r in cleared]})
            if any(r.device_type != "caller" for r in cleared):
                await self._tell_twin("clear_quarantine", device_id, cleared[0].zone_id, f"guardian: {reason}")
        return cleared

    async def on_verdict(self, v: Verdict) -> None:
        """Count clean readings of a contained sensor; release after N clean readings and the cooldown."""
        changed = False
        for kind in ("isolation", "quarantine"):
            r = self.records.get((v.sensor_id, kind))
            if not r or not r.active or r.device_type != "sensor":
                continue
            r.good_readings = r.good_readings + 1 if v.raw_status == Status.trusted else 0
            changed = True
            self.db.put_containment(r)
        if changed and all(release_ready(r, self.clock.now(), self.cfg.release_after_good_readings)
                           for k in ("isolation", "quarantine")
                           if (r := self.records.get((v.sensor_id, k))) and r.active):
            await self.clear(v.sensor_id, f"{self.cfg.release_after_good_readings} consecutive clean readings",
                             manual=False)
