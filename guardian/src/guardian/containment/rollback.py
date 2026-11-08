"""Rollback view: the latest *usable* value of a sensor, falling back to last-known-good when contained."""

from __future__ import annotations

from typing import Any

from guardian.clock import iso
from guardian.ingest.state_store import SensorState
from guardian.models import Status


def latest_usable(s: SensorState, contained_reason: str | None, stale: bool) -> dict[str, Any]:
    v = s.latest_verdict
    latest = s.latest_reading
    reason = contained_reason
    if reason is None and v is not None and v.status == Status.untrusted:
        reason = "latest_untrusted"
    if reason is not None:
        if s.lkg is None:
            return {"sensor_id": s.sensor_id, "value": None, "ts": None, "sequence_no": None,
                    "status": Status.unknown.value, "rolled_back": True, "reason": f"{reason}; no last-known-good",
                    "verdict_id": v.verdict_id if v else None, "stale": stale}
        return {"sensor_id": s.sensor_id, "value": s.lkg.value, "ts": iso(s.lkg.ts),
                "sequence_no": s.lkg.sequence_no, "status": Status.trusted.value, "rolled_back": True,
                "reason": reason, "verdict_id": v.verdict_id if v else None, "stale": stale}
    status = Status.unknown if stale or v is None else v.status
    return {"sensor_id": s.sensor_id, "value": latest.value if latest else None,
            "ts": iso(latest.ts) if latest else None, "sequence_no": latest.sequence_no if latest else None,
            "status": status.value, "rolled_back": False, "reason": "stale" if stale else None,
            "verdict_id": v.verdict_id if v else None, "stale": stale}
