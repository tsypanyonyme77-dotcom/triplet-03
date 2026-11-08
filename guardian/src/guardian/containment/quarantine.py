"""Release hysteresis: N consecutive clean readings and a cooldown that grows with each re-containment."""

from __future__ import annotations

from datetime import datetime

from guardian.models import ContainmentRecord


def cooldown_for(base_s: float, backoff: float, previous_releases: int) -> float:
    return base_s * (backoff ** previous_releases)


def release_ready(r: ContainmentRecord, now: datetime, good_needed: int) -> bool:
    return r.good_readings >= good_needed and (now - r.since).total_seconds() >= r.cooldown_s
